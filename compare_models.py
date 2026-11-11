"""
Head-to-head: Model 1 (conditional-logit + XGBoost blend, models/mvp_model.joblib) vs.
Model 2 (Random Forest + XGBoost ensemble, models/model2_ensemble.joblib) on one season,
by default the in-progress 2026-27 season (SEASON_ID 2027).

Usage:
    python compare_models.py                       # 2026-27, re-pulls current stats
    python compare_models.py --no-refresh          # reuse today's cached pull
    python compare_models.py --min-games 10        # override the games-played threshold
    python compare_models.py --legacy-darko-merge  # DPM merged the way Model 2's training data was
    python compare_models.py --save-db             # also store today's MVP, ROY and DPOY snapshots (TiDB)
    python compare_models.py --skip-awards         # MVP only (no ROY/DPOY)

DARKO: the current season reads data/raw/darko_live.csv (refresh it with `python download_darko.py`);
past seasons read data/raw/darko_<season>.csv. --darko-file overrides either.
"""
from __future__ import annotations

import argparse
import re
import time
from datetime import date, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from nba_api.stats.endpoints import teamplayeronoffsummary

import data_pipeline as dp
import model_trainer  # noqa: F401 - needed so the Model 1 bundle can unpickle model_trainer.Blend
from model_trainer import MODEL_DIR, prepare_features

ONOFF_TOP_N = 25     # Model 2 pulled on/off only for the top 25 by VORP per season
ONOFF_SLEEP = 2.0
CURRENT_SEASON = 2027                          # 2026-27, the season darko_live.csv covers
LIVE_DARKO = dp.RAW_DIR / "darko_live.csv"     # written by download_darko.py
STALE_DAYS = 2
# MVP baseline: every MVP since 1980 averaged well above both. Applied after scoring and before
# ranking, so it changes who is ranked, never a player's model scores or the model weights.
MVP_MIN_PTS = 15.0
MVP_MIN_MPG = 28.0


# --------------------------------------------------------------------------- season data
def load_season(season_id: int, refresh: bool) -> pd.DataFrame:
    """Box scores, standings and bbref advanced stats with season-relative Z-scores.
    Eligibility thresholds scale with the most games any team has played so far."""
    return prepare_features(dp.build_dataset(season_id, season_id, refresh=refresh))


def darko_path(season_id: int, override: str | None = None) -> Path:
    """Live file for the current season, archived darko_<season>.csv otherwise."""
    if override:
        path = Path(override)
    elif season_id == CURRENT_SEASON:
        path = LIVE_DARKO
        if not path.exists():
            raise FileNotFoundError(f"{path} not found - run `python download_darko.py` "
                                    f"(or pass --darko-file data/raw/darko_{season_id}.csv)")
    else:
        path = dp.RAW_DIR / f"darko_{season_id}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    print(f"DARKO file: {path.name} (updated {age.days}d {age.seconds // 3600}h ago)")
    if path == LIVE_DARKO and age.days >= STALE_DAYS:
        print(f"  ! {path.name} is {age.days} days old - run `python download_darko.py` for current DPM")
    return path


def add_darko(df: pd.DataFrame, season_id: int, legacy: bool, darko_file: str | None = None) -> pd.DataFrame:
    path = darko_path(season_id, darko_file)
    darko = pd.read_csv(path, encoding="utf-8-sig")
    darko["DPM"] = pd.to_numeric(darko["DPM"].astype(str).str.replace("+", "", regex=False), errors="coerce")

    if legacy:
        # Same key as the notebook merge used for Model 2's training data. Accented letters are
        # deleted rather than folded, so e.g. "Nikola Jokić" never matches DARKO's "Nikola Jokic".
        key = lambda s: s.str.lower().str.replace(r"[^a-z\s]", "", regex=True)  # noqa: E731
        m = darko.assign(K=key(darko["Player"])).drop_duplicates("K").set_index("K")["DPM"]
        df["DPM"] = key(df["PLAYER"]).map(m)
    else:
        # Prefer DARKO's NBA ID (same ID space as nba_api PLAYER_ID); fall back to accent-folded names.
        df["DPM"] = np.nan
        if "NBA ID" in darko.columns:
            by_id = darko.dropna(subset=["NBA ID"]).assign(ID=lambda d: d["NBA ID"].astype(int).astype(str))
            df["DPM"] = df["PLAYER_ID"].astype(str).map(by_id.drop_duplicates("ID").set_index("ID")["DPM"])
        by_name = darko.assign(K=darko["Player"].map(dp.normalize_name)).drop_duplicates("K").set_index("K")["DPM"]
        df["DPM"] = df["DPM"].fillna(df["NAME_KEY"].map(by_name))

    matched = df["DPM"].notna()
    print(f"DARKO {path.name}: matched {matched.sum()} of {len(df)} players "
          f"({(matched & df['ELIGIBLE_NOLABEL']).sum()} of {df['ELIGIBLE_NOLABEL'].sum()} eligible)")
    df["DPM"] = df["DPM"].fillna(0)  # same fill as Model 2's training data

    pool = df[df["IN_REF_POOL"] & df["HAS_ADV"]]["DPM"]
    df["Z_DPM"] = (df["DPM"] - pool.mean()) / pool.std(ddof=0)
    return df


def add_on_off(df: pd.DataFrame, season_id: int, refresh: bool) -> pd.DataFrame:
    """Team on/off net rating for the top 25 players by VORP (0 for everyone else), as in Model 2.
    One API call per team containing a candidate; cached to data/raw/onoff_<season>.parquet."""
    cand = df[df["HAS_ADV"] & df["TEAM_ID"].notna()].nlargest(ONOFF_TOP_N, "VORP")
    cache = dp.RAW_DIR / f"onoff_{season_id}.parquet"

    onoff = pd.read_parquet(cache) if cache.exists() and not refresh else None
    if onoff is None or "TEAM_ID" not in onoff.columns:  # older caches lack TEAM_ID
        rows = []
        teams = sorted(cand["TEAM_ID"].astype(int).unique())
        print(f"Pulling on/off for {len(cand)} candidates across {len(teams)} teams ...")
        for team_id in teams:
            try:
                res = dp.nba_call(lambda: teamplayeronoffsummary.TeamPlayerOnOffSummary(
                    team_id=team_id, season=dp.season_label(season_id),
                    measure_type_detailed_defense="Advanced", timeout=dp.NBA_TIMEOUT).get_data_frames(),
                    f"on/off team {team_id}")
            except dp.NBAUnreachableError:
                raise  # blocked: stop now rather than time out once per team (and don't cache nothing)
            except RuntimeError as e:
                print(f"  ! skipped team {team_id}: {e}")
                continue
            on, off = res[1], res[2]
            m = on[["VS_PLAYER_ID", "NET_RATING"]].merge(
                off[["VS_PLAYER_ID", "NET_RATING"]], on="VS_PLAYER_ID", suffixes=("_ON", "_OFF"))
            rows.append(pd.DataFrame({"PLAYER_ID": m["VS_PLAYER_ID"].astype(str), "TEAM_ID": team_id,
                                      "on_off_net_rtg": m["NET_RATING_ON"] - m["NET_RATING_OFF"]}))
            time.sleep(ONOFF_SLEEP)
        onoff = (pd.concat(rows, ignore_index=True) if rows
                 else pd.DataFrame(columns=["PLAYER_ID", "TEAM_ID", "on_off_net_rtg"]))
        onoff.to_parquet(cache, index=False)

    # Key on (player, listed team): a traded player appears in each of their teams' responses
    lookup = onoff.assign(TEAM_ID=onoff["TEAM_ID"].astype(int)).set_index(["PLAYER_ID", "TEAM_ID"])["on_off_net_rtg"]
    keys = pd.MultiIndex.from_arrays([df["PLAYER_ID"].astype(str), df["TEAM_ID"].fillna(0).astype(int)])
    vals = pd.Series(lookup.reindex(keys).to_numpy(), index=df.index)
    is_cand = df.index.isin(cand.index)
    df["on_off_net_rtg"] = np.where(is_cand, vals, np.nan)
    df["on_off_net_rtg"] = df["on_off_net_rtg"].fillna(0)
    return df


# --------------------------------------------------------------------------- models
def score_model1(pool: pd.DataFrame) -> pd.DataFrame:
    b = joblib.load(MODEL_DIR / "mvp_model.joblib")
    blend = b["model"].predict(pool[b["features"]].to_numpy())
    lo, hi = b["anchors"]
    pool["M1_INDEX"] = np.clip(100 * (blend - lo) / (hi - lo), 0, 100)
    pool["M1_SHARE"] = b["calibrator"].predict(blend)
    return pool


def score_model2(pool: pd.DataFrame) -> pd.DataFrame:
    b = joblib.load(MODEL_DIR / "model2_ensemble.joblib")
    X = pool[b["features"]]
    pool["M2_SHARE"] = np.clip((b["rf"].predict(X) + b["xgb"].predict(X)) / 2, 0, 1)
    return pool


def score_dominance(pool: pd.DataFrame) -> pd.DataFrame:
    """MVP Dominance Index (mvp_index.py): MVP_INDEX = m * RAW_DOMINANCE + b, unclipped."""
    path = MODEL_DIR / "mvp_index_bundle.joblib"
    if not path.exists():
        print(f"(no {path.name} - run `python mvp_index.py` to add the Dominance Index)")
        pool["MVP_INDEX"] = np.nan
        return pool
    b = joblib.load(path)
    w = pd.Series(b["weights"])[b["features"]]
    pool["RAW_DOMINANCE"] = pool[b["features"]].to_numpy() @ w.to_numpy()
    pool["MVP_INDEX"] = b["m"] * pool["RAW_DOMINANCE"] + b["b"]
    return pool


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, default=CURRENT_SEASON, help="season end year (2027 = 2026-27)")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--no-refresh", action="store_true", help="use cached data instead of re-pulling")
    ap.add_argument("--min-games", type=float, default=None, help="override games-played threshold")
    ap.add_argument("--min-mpg", type=float, default=dp.MIN_MPG)
    ap.add_argument("--mvp-min-pts", type=float, default=MVP_MIN_PTS,
                    help="MVP baseline: minimum points per game to be ranked (default %(default)s)")
    ap.add_argument("--skip-awards", action="store_true",
                    help="MVP only: skip the ROY and DPOY predictions (award_inference.py)")
    ap.add_argument("--mvp-min-mpg", type=float, default=MVP_MIN_MPG,
                    help="MVP baseline: minimum minutes per game to be ranked (default %(default)s)")
    ap.add_argument("--legacy-darko-merge", action="store_true",
                    help="merge DPM by the notebook's name key (reproduces Model 2's training data)")
    ap.add_argument("--darko-file", default=None,
                    help="DARKO CSV to use instead of darko_live.csv / darko_<season>.csv")
    ap.add_argument("--save-db", action="store_true",
                    help="write every eligible player's scores to the daily_predictions table (DATABASE_URL in .env)")
    a = ap.parse_args()
    refresh = not a.no_refresh

    df = load_season(a.season, refresh)
    df = add_darko(df, a.season, a.legacy_darko_merge, a.darko_file)
    df = add_on_off(df, a.season, refresh)
    df["IS_ROOKIE"] = df["PLAYER_ID"].astype(str).isin(dp.fetch_rookie_ids(a.season, refresh))

    games_so_far = int(df["SEASON_GAMES"].iloc[0])
    min_games = a.min_games if a.min_games is not None else float(df["MIN_GAMES_REQ"].iloc[0])
    pool = df[df["HAS_ADV"] & (df["MPG"] >= a.min_mpg) & (df["GP"] >= min_games)].copy()
    if pool.empty:
        raise SystemExit("No players pass the eligibility filter - lower --min-games / --min-mpg")

    pool = score_dominance(score_model2(score_model1(pool)))


    # MVP baseline filter: drop low-usage players whose early-season impact metrics run hot
    baseline = (pool["PTS"] >= a.mvp_min_pts) & (pool["MPG"] >= a.mvp_min_mpg)
    would_rank = pool["M2_SHARE"].rank(ascending=False, method="first")
    cut = pool[~baseline & (would_rank <= a.top)].sort_values("M2_SHARE", ascending=False)
    n_eligible = len(pool)
    pool = pool[baseline].copy()
    if pool.empty:
        raise SystemExit("No players pass the MVP baseline - lower --mvp-min-pts / --mvp-min-mpg")

    pool["M1_RANK"] = pool["M1_INDEX"].rank(ascending=False, method="first").astype(int)
    pool["M2_RANK"] = pool["M2_SHARE"].rank(ascending=False, method="first").astype(int)

    print(f"\n{dp.season_label(a.season)} - most games played by any team: {games_so_far}. "
          f"Eligible: >= {min_games:.1f} GP and >= {a.min_mpg:.0f} MPG -> {n_eligible} players")
    print(f"MVP baseline: >= {a.mvp_min_pts:g} PTS and >= {a.mvp_min_mpg:g} MPG -> {len(pool)} ranked")
    if len(cut):
        print(f"  removed from the Model 2 top {a.top}: " + ", ".join(
            f"{r.PLAYER} ({r.PTS:.1f} PTS, {r.MPG:.1f} MPG)" for r in cut.itertuples()))
    if games_so_far < 20:
        print("Early season: samples are tiny and Z-scores swing a lot game to game. Treat this as a snapshot.")

    n = a.top
    m1 = pool.nsmallest(n, "M1_RANK").reset_index(drop=True)
    m2 = pool.nsmallest(n, "M2_RANK").reset_index(drop=True)
    side = pd.DataFrame({
        "Rank": range(1, len(m1) + 1),
        "Model 1": m1["PLAYER"] + " (" + m1["TEAM"] + ")",
        "M1 Index": m1["M1_INDEX"].round(1),
        "M1 Share": m1["M1_SHARE"].round(3),
        "M1 Dom Index": m1["MVP_INDEX"].round(1),
        "M2 rank of M1 pick": m1["M2_RANK"],
        " | ": "|",
        "Model 2": m2["PLAYER"] + " (" + m2["TEAM"] + ")",
        "M2 Share": m2["M2_SHARE"].round(3),
        "M2 Dom Index": m2["MVP_INDEX"].round(1),
        "M1 rank of M2 pick": m2["M1_RANK"],
    })
    pd.set_option("display.width", 250)
    print(f"\nTop {n} MVP leaderboard - Model 1 vs. Model 2 (Dom Index = unbounded MVP Dominance Index, "
          f"35 = median player, 82 = average MVP)\n")
    print(side.to_string(index=False))

    both = set(m1["PLAYER_ID"]) & set(m2["PLAYER_ID"])
    print(f"\nAgreement: {len(both)}/{n} players in both top {n}; "
          f"#1 pick {'agrees' if m1.loc[0, 'PLAYER_ID'] == m2.loc[0, 'PLAYER_ID'] else 'differs'}.")

    cols = ["PLAYER", "TEAM", "GP", "MPG", "PTS", "TS_PCT", "BPM", "VORP", "TEAM_WIN_PCT", "DPM", "on_off_net_rtg"]
    top = pool[pool["PLAYER_ID"].isin(set(m1["PLAYER_ID"]) | set(m2["PLAYER_ID"]))]
    print("\nInputs for every player in either top list:")
    print(top.sort_values("M2_RANK")[cols + ["MVP_INDEX", "M1_RANK", "M2_RANK"]].round(3).to_string(index=False))

    # ROY and DPOY: trained award models (award_inference.py). Isolated so a failure here never blocks
    # the MVP update; it is reported and makes the run exit non-zero at the end.
    awards, award_error = None, None
    if not a.skip_awards:
        try:
            from award_inference import print_races, run_award_predictions
            awards = run_award_predictions(a.season, refresh=refresh)
            print_races(awards, top=a.top)
        except Exception as e:  # noqa: BLE001
            award_error = f"{type(e).__name__}: {e}"
            print(f"\n!! ROY/DPOY predictions failed: {award_error}")

    if a.save_db:
        from db_sync import get_engine, write_daily_dpoy, write_daily_predictions, write_daily_roy  # --save-db only

        engine = get_engine()
        n_saved = write_daily_predictions(engine, pool, season_id=a.season)
        print(f"\nSaved {n_saved} live players for {dp.season_label(a.season)} ({date.today()}) "
              f"to daily_predictions on {engine.url.host or engine.url.database}")
        if awards is not None:
            try:
                n_roy = write_daily_roy(engine, awards["roy"], season_id=a.season)
                n_dpoy = write_daily_dpoy(engine, awards["dpoy"], season_id=a.season)
                print(f"Saved {n_roy} rookies to daily_roy_predictions and {n_dpoy} candidates to daily_dpoy_predictions")
            except Exception as e:  # noqa: BLE001
                award_error = f"saving ROY/DPOY failed: {type(e).__name__}: {e}"
                print(f"!! {award_error}")

    if award_error:
        raise SystemExit(f"\nERROR (MVP results were still produced{' and saved' if a.save_db else ''}): {award_error}")


if __name__ == "__main__":
    try:
        main()
    except dp.NBAUnreachableError as e:
        raise SystemExit(f"\nERROR: {e}") from None
