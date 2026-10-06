"""
Phase 1 - Data engineering & cross-era standardization for the NBA MVP Index.

Sources (all cached per season under data/raw/ as Parquet):
  * nba_api  leaguedashplayerstats (Base, PerGame) -> PTS/REB/AST/STL/BLK/TOV/MPG/GP
  * nba_api  leaguestandingsv3                     -> team W/L, season length
  * basketball-reference advanced table            -> TS%, USG%, PER, WS, WS/48, BPM, VORP
  * basketball-reference awards page               -> MVP voting (Pts Won / Pts Max = Share)

Why basketball-reference: stats.nba.com has no BPM / VORP / Win Shares, no advanced
(TS%, USG%) data before 1996-97, and no MVP vote shares at all.

Season convention: `season_id` is the year the season ENDS (2024 == 2023-24).

Usage:
    python data_pipeline.py --start 2021 --end 2024      # 3-season smoke test
    python data_pipeline.py --start 1980 --end 2026      # full pull
    python data_pipeline.py --start 2021 --end 2024 --refresh   # ignore cache
"""
from __future__ import annotations

import argparse
import io
import re
import time
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from nba_api.stats.endpoints import leaguedashplayerstats, leaguestandingsv3

ROOT = Path(__file__).parent
RAW_DIR = ROOT / "data" / "raw"
PROC_DIR = ROOT / "data" / "processed"

NBA_API_SLEEP = 1.5      # seconds between stats.nba.com calls
BBREF_SLEEP = 4.0        # bbref allows ~20 req/min; stay well under
MIN_MPG = 20.0           # eligibility: minutes per game
GAMES_FRACTION = 65 / 82  # strict eligibility (2023-24 onward): 65 of 82 games
HIST_GAMES_FRACTION = 50 / 82  # relaxed eligibility for training seasons (<= 2022-23): 50 of 82
STRICT_FROM_SEASON = 2024  # season_id (end year) of 2023-24, first season with the 65-game rule
REF_MIN_MPG = 15.0       # "rotation" pool used as the reference population for Z-scores
REF_GAMES_FRACTION = 0.40

HEADERS = {"User-Agent": "Mozilla/5.0 (personal research project; low request rate)"}

NBA_API_FIRST_SEASON = 1997  # stats.nba.com player tables start in 1996-97 (season_id 1997)

# bbref team abbreviation -> franchise nickname as used by nba_api standings (pre-1997 seasons only)
BBREF_TEAM_NICKNAME = {
    "ATL": "Hawks", "BOS": "Celtics", "NJN": "Nets", "BRK": "Nets", "CHI": "Bulls", "CHH": "Hornets",
    "CLE": "Cavaliers", "DAL": "Mavericks", "DEN": "Nuggets", "DET": "Pistons", "GSW": "Warriors",
    "HOU": "Rockets", "IND": "Pacers", "KCK": "Kings", "SAC": "Kings", "LAC": "Clippers", "SDC": "Clippers",
    "LAL": "Lakers", "MIA": "Heat", "MIL": "Bucks", "MIN": "Timberwolves", "NYK": "Knicks", "PHI": "76ers",
    "PHO": "Suns", "POR": "Trail Blazers", "SAS": "Spurs", "SEA": "SuperSonics", "UTA": "Jazz",
    "WSB": "Bullets", "WAS": "Bullets", "ORL": "Magic", "TOR": "Raptors", "VAN": "Grizzlies",
}

# Columns that get an era-normalized Z-score.
Z_FEATURES = [
    "PTS", "REB", "AST", "STL", "BLK", "TOV", "MPG",
    "TS_PCT", "USG_PCT", "PER", "WS", "WS_48", "BPM", "VORP",
    "TEAM_WIN_PCT",
]


# --------------------------------------------------------------------------- helpers
def season_label(season_id: int) -> str:
    """2024 -> '2023-24'."""
    return f"{season_id - 1}-{str(season_id)[-2:]}"


def normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = s.lower().replace(".", "").replace("'", "").replace("-", " ")
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _cached(path: Path, fetch, refresh: bool) -> pd.DataFrame:
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = fetch()
    df.to_parquet(path, index=False)
    return df


def _retry(fn, what: str, tries: int = 4, base_sleep: float = 5.0):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - network layer, want to retry anything
            if i == tries - 1:
                raise RuntimeError(f"{what} failed after {tries} tries: {e}") from e
            wait = base_sleep * (2 ** i)
            print(f"    ! {what}: {type(e).__name__}: {str(e)[:80]} - retry in {wait:.0f}s")
            time.sleep(wait)


def _bbref_tables(url: str, **read_html_kwargs) -> list[pd.DataFrame]:
    def go():
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 60)))
            raise RuntimeError("429 rate limited")
        r.raise_for_status()
        return pd.read_html(io.StringIO(r.content.decode("utf-8")), **read_html_kwargs)

    out = _retry(go, f"GET {url}")
    time.sleep(BBREF_SLEEP)
    return out


# --------------------------------------------------------------------------- fetchers
def fetch_bbref_pergame(season_id: int, refresh: bool) -> pd.DataFrame:
    """Per-game box scores for seasons before stats.nba.com has data (1979-80 .. 1995-96).
    Returns the same columns as fetch_nba_base (PLAYER_ID is a synthetic name|age key)."""
    def fetch():
        t = _bbref_tables(f"https://www.basketball-reference.com/leagues/NBA_{season_id}_per_game.html")[0]
        t = t[t["Player"].notna() & (t["Player"] != "Player")].copy()
        t["Team"] = t["Team"].astype(str)
        total = t["Team"].str.fullmatch(r"\dTM|TOT")
        last_team = t[~total].groupby("Player")["Team"].last()  # latest stint = player's current team
        multi = t.groupby("Player")["Player"].transform("size") > 1
        t = t[(~multi) | total].copy()
        t["Team"] = np.where(total[t.index], t["Player"].map(last_team), t["Team"])
        out = pd.DataFrame({
            "PLAYER_ID": t["Player"].map(normalize_name) + "|" + t["Age"].astype(str),
            "PLAYER_NAME": t["Player"], "TEAM_ID": 0, "TEAM_ABBREVIATION": t["Team"],
            "AGE": pd.to_numeric(t["Age"], errors="coerce"), "GP": pd.to_numeric(t["G"], errors="coerce"),
            "MIN": pd.to_numeric(t["MP"], errors="coerce"), "PTS": pd.to_numeric(t["PTS"], errors="coerce"),
            "REB": pd.to_numeric(t["TRB"], errors="coerce"), "AST": pd.to_numeric(t["AST"], errors="coerce"),
            "STL": pd.to_numeric(t["STL"], errors="coerce"), "BLK": pd.to_numeric(t["BLK"], errors="coerce"),
            "TOV": pd.to_numeric(t["TOV"], errors="coerce"),
        })
        return out.drop_duplicates("PLAYER_ID").reset_index(drop=True)

    return _cached(RAW_DIR / f"bbref_pergame_{season_id}.parquet", fetch, refresh)


def fetch_nba_base(season_id: int, refresh: bool) -> pd.DataFrame:
    if season_id < NBA_API_FIRST_SEASON:
        return fetch_bbref_pergame(season_id, refresh)

    def fetch():
        df = _retry(
            lambda: leaguedashplayerstats.LeagueDashPlayerStats(
                season=season_label(season_id),
                per_mode_detailed="PerGame",
                measure_type_detailed_defense="Base",
                timeout=60,
            ).get_data_frames()[0],
            f"nba_api base {season_id}",
        )
        time.sleep(NBA_API_SLEEP)
        return df[["PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "TEAM_ABBREVIATION", "AGE", "GP",
                   "MIN", "PTS", "REB", "AST", "STL", "BLK", "TOV"]]

    return _cached(RAW_DIR / f"nba_base_{season_id}.parquet", fetch, refresh)


def fetch_standings(season_id: int, refresh: bool) -> pd.DataFrame:
    def fetch():
        df = _retry(
            lambda: leaguestandingsv3.LeagueStandingsV3(
                season=season_label(season_id), timeout=60
            ).get_data_frames()[0],
            f"nba_api standings {season_id}",
        )
        time.sleep(NBA_API_SLEEP)
        return df[["TeamID", "TeamName", "WINS", "LOSSES", "WinPCT"]]

    return _cached(RAW_DIR / f"standings_{season_id}.parquet", fetch, refresh)


def fetch_bbref_advanced(season_id: int, refresh: bool) -> pd.DataFrame:
    def fetch():
        t = _bbref_tables(f"https://www.basketball-reference.com/leagues/NBA_{season_id}_advanced.html")[0]
        t = t[t["Player"].notna() & (t["Player"] != "Player")].copy()
        t["Tm_is_total"] = t["Team"].astype(str).str.fullmatch(r"\dTM|TOT")
        keep = ["Player", "Team", "Tm_is_total", "G", "MP", "PER", "TS%", "USG%", "WS", "WS/48", "BPM", "VORP"]
        t = t[keep].rename(columns={"TS%": "TS_PCT", "USG%": "USG_PCT", "WS/48": "WS_48",
                                    "G": "BB_G", "MP": "BB_MP", "Player": "BB_NAME", "Team": "BB_TEAM"})
        # Keep one row per player: the combined multi-team row if the player was traded.
        t["_n_rows"] = t.groupby("BB_NAME")["BB_NAME"].transform("size")
        t = t[(t["_n_rows"] == 1) | t["Tm_is_total"]].drop(columns=["_n_rows"])
        for c in ["BB_G", "BB_MP", "PER", "TS_PCT", "USG_PCT", "WS", "WS_48", "BPM", "VORP"]:
            t[c] = pd.to_numeric(t[c], errors="coerce")
        t["NAME_KEY"] = t["BB_NAME"].map(normalize_name)
        return t.reset_index(drop=True)

    return _cached(RAW_DIR / f"bbref_adv_{season_id}.parquet", fetch, refresh)


def fetch_bbref_mvp(season_id: int, refresh: bool) -> pd.DataFrame:
    def fetch():
        tables = _bbref_tables(f"https://www.basketball-reference.com/awards/awards_{season_id}.html", header=1)
        mvp = next(t for t in tables if {"Pts Won", "Pts Max", "Share"} <= set(t.columns))
        mvp = mvp[mvp["Player"].notna() & (mvp["Player"] != "Player")].copy()
        out = pd.DataFrame({
            "BB_NAME": mvp["Player"],
            "MVP_RANK": pd.to_numeric(mvp["Rank"].astype(str).str.replace("T", ""), errors="coerce"),
            "MVP_PTS_WON": pd.to_numeric(mvp["Pts Won"], errors="coerce"),
            "MVP_PTS_MAX": pd.to_numeric(mvp["Pts Max"], errors="coerce"),
        })
        out["MVP_SHARE"] = out["MVP_PTS_WON"] / out["MVP_PTS_MAX"]
        out["NAME_KEY"] = out["BB_NAME"].map(normalize_name)
        return out.drop(columns=["BB_NAME"])

    return _cached(RAW_DIR / f"bbref_mvp_{season_id}.parquet", fetch, refresh)


# --------------------------------------------------------------------------- assembly
def build_season(season_id: int, refresh: bool = False) -> pd.DataFrame:
    """One row per player-season with raw stats, team win%, MVP share and eligibility flags
    (no Z-scores yet - those need the full season population)."""
    base = fetch_nba_base(season_id, refresh).copy()
    base["PLAYER_ID"] = base["PLAYER_ID"].astype(str)
    stand = fetch_standings(season_id, refresh)
    if season_id < NBA_API_FIRST_SEASON:
        # bbref has no franchise IDs: join to standings through the team nickname
        ids = stand.set_index("TeamName")["TeamID"]
        base["TEAM_ID"] = base["TEAM_ABBREVIATION"].map(BBREF_TEAM_NICKNAME).map(ids)
    adv = fetch_bbref_advanced(season_id, refresh)
    try:
        mvp = fetch_bbref_mvp(season_id, refresh)
    except Exception as e:  # noqa: BLE001 - voting page doesn't exist yet for in-progress seasons
        print(f"  (no MVP voting available for {season_id}: {str(e)[:60]}; labels set to 0)")
        mvp = pd.DataFrame({"NAME_KEY": [], "MVP_RANK": [], "MVP_SHARE": []})

    season_games = int((stand["WINS"] + stand["LOSSES"]).max())

    df = base.rename(columns={"MIN": "MPG", "PLAYER_NAME": "PLAYER", "TEAM_ABBREVIATION": "TEAM"})
    df["NAME_KEY"] = df["PLAYER"].map(normalize_name)

    # Merge bbref advanced; if two bbref players share a normalized name, keep the one whose
    # games-played is closest to nba_api's.
    m = df.merge(adv.drop(columns=["Tm_is_total"]), on="NAME_KEY", how="left")
    m["_gdiff"] = (m["GP"] - m["BB_G"]).abs().fillna(1e9)
    m = m.sort_values("_gdiff").drop_duplicates("PLAYER_ID").drop(columns="_gdiff")
    bad = m["BB_G"].notna() & ((m["GP"] - m["BB_G"]).abs() > 3)
    m.loc[bad, ["BB_NAME", "PER", "TS_PCT", "USG_PCT", "WS", "WS_48", "BPM", "VORP"]] = np.nan

    m = m.merge(mvp[["NAME_KEY", "MVP_RANK", "MVP_SHARE"]].drop_duplicates("NAME_KEY"),
                on="NAME_KEY", how="left")
    m["MVP_SHARE"] = m["MVP_SHARE"].fillna(0.0)

    st = stand.rename(columns={"TeamID": "TEAM_ID", "WinPCT": "TEAM_WIN_PCT"})[["TEAM_ID", "TEAM_WIN_PCT"]]
    m = m.merge(st, on="TEAM_ID", how="left")

    m["SEASON_ID"] = season_id
    m["SEASON"] = season_label(season_id)
    m["SEASON_GAMES"] = season_games
    if season_id >= STRICT_FROM_SEASON:
        m["MIN_GAMES_REQ"] = GAMES_FRACTION * season_games
        m["ELIGIBLE"] = (m["MPG"] >= MIN_MPG) & (m["GP"] >= m["MIN_GAMES_REQ"])
    else:
        # Historical training seasons: relaxed games threshold, and anyone who got MVP votes stays in.
        m["MIN_GAMES_REQ"] = HIST_GAMES_FRACTION * season_games
        m["ELIGIBLE"] = ((m["MPG"] >= MIN_MPG) & (m["GP"] >= m["MIN_GAMES_REQ"])) | (m["MVP_SHARE"] > 0)
    m["IN_REF_POOL"] = (m["MPG"] >= REF_MIN_MPG) & (m["GP"] >= REF_GAMES_FRACTION * season_games)
    m["HAS_ADV"] = m[["TS_PCT", "USG_PCT", "WS", "BPM", "VORP"]].notna().all(axis=1)
    return m


def add_era_features(df: pd.DataFrame) -> pd.DataFrame:
    """Per-season Z-scores, rTS%, and the Carry Proxy.

    Mean/std come from the season's *rotation pool* (>=15 mpg and >=40% of games), so that a
    season's baseline reflects real NBA rotation players rather than just the 30-ish stars that
    pass the eligibility filter. Z-scores are then computed for every player against that
    baseline, and the eligibility filter is applied to the output rows.
    """
    df = df.copy()
    pool = df[df["IN_REF_POOL"] & df["HAS_ADV"]]
    g = pool.groupby("SEASON_ID")
    for col in Z_FEATURES:
        mu = df["SEASON_ID"].map(g[col].mean())
        sd = df["SEASON_ID"].map(g[col].std(ddof=0))
        df[f"Z_{col}"] = (df[col] - mu) / sd

    # rTS% = TS% minus the rotation-pool league average, in percentage points.
    df["RTS"] = (df["TS_PCT"] - df["SEASON_ID"].map(g["TS_PCT"].mean())) * 100
    df["CARRY_PROXY"] = df["Z_USG_PCT"] * df["RTS"]
    return _zscore_carry(df)


def _zscore_carry(df: pd.DataFrame) -> pd.DataFrame:
    pool = df[df["IN_REF_POOL"] & df["HAS_ADV"]]
    g = pool.groupby("SEASON_ID")["CARRY_PROXY"]
    df["Z_CARRY_PROXY"] = (df["CARRY_PROXY"] - df["SEASON_ID"].map(g.mean())) / df["SEASON_ID"].map(g.std(ddof=0))
    return df


def build_dataset(start: int, end: int, refresh: bool = False) -> pd.DataFrame:
    frames = []
    for sid in range(start, end + 1):
        print(f"[{sid}] {season_label(sid)} ...", flush=True)
        try:
            frames.append(build_season(sid, refresh))
        except Exception as e:  # noqa: BLE001
            print(f"  !! skipped {sid}: {e}")
    if not frames:
        raise SystemExit("No seasons built.")
    frames = [f for f in frames if len(f)]
    allp = pd.concat(frames, ignore_index=True)
    return add_era_features(allp)


# --------------------------------------------------------------------------- reporting
def report(allp: pd.DataFrame) -> None:
    print("\n=== Data quality report ===")
    for sid, s in allp.groupby("SEASON_ID"):
        el = s[s["ELIGIBLE"]]
        lost = s[~s["ELIGIBLE"] & (s["MVP_SHARE"] > 0)]
        winner = s.loc[s["MVP_SHARE"].idxmax()]
        w_ok = bool(winner["ELIGIBLE"])
        print(f"{season_label(sid)}: players={len(s)} eligible={len(el)} "
              f"(>= {s['MIN_GAMES_REQ'].iloc[0]:.1f} of {s['SEASON_GAMES'].iloc[0]} games, >= {MIN_MPG:.0f} mpg) "
              f"ref_pool={int(s['IN_REF_POOL'].sum())}")
        print(f"   MVP: {winner['PLAYER']} (share {winner['MVP_SHARE']:.3f}) eligible={w_ok} "
              f"| vote-getters filtered out: {len(lost)} (share lost {lost['MVP_SHARE'].sum():.3f})")
        miss = el[~el["HAS_ADV"]]
        if len(miss):
            print(f"   !! eligible players missing bbref advanced stats: {miss['PLAYER'].tolist()}")
        z = el[[f"Z_{c}" for c in Z_FEATURES]]
        print(f"   eligible-pool Z mean range [{z.mean().min():+.2f}, {z.mean().max():+.2f}] "
              f"(rotation-pool Z has mean 0 / sd 1 by construction)")
        votes = s["MVP_SHARE"].sum()
        print(f"   total share matched across players: {votes:.3f}")
    print("\nSanity check: reference-pool Z mean/std per season (should be ~0 / ~1):")
    pool = allp[allp["IN_REF_POOL"] & allp["HAS_ADV"]]
    chk = pool.groupby("SEASON_ID")[["Z_PTS", "Z_BPM", "Z_TEAM_WIN_PCT", "Z_CARRY_PROXY"]].agg(["mean", "std"]).round(3)
    print(chk.to_string())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=2021)
    ap.add_argument("--end", type=int, default=2024)
    ap.add_argument("--refresh", action="store_true", help="ignore cached raw files")
    ap.add_argument("--out", default=None, help="processed parquet path")
    a = ap.parse_args()

    allp = build_dataset(a.start, a.end, a.refresh)
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(a.out) if a.out else PROC_DIR / f"player_seasons_{a.start}_{a.end}.parquet"
    allp.to_parquet(out, index=False)
    report(allp)

    el = allp[allp["ELIGIBLE"] & allp["HAS_ADV"]]
    print(f"\nSaved {len(allp)} player-seasons ({len(el)} eligible) -> {out}")
    cols = ["SEASON", "PLAYER", "TEAM", "GP", "MPG", "PTS", "TS_PCT", "USG_PCT", "BPM", "WS_48",
            "TEAM_WIN_PCT", "CARRY_PROXY", "MVP_SHARE"]
    for sid, s in el.groupby("SEASON_ID"):
        print(f"\nTop 5 eligible by BPM-Z in {season_label(sid)} (with actual MVP share):")
        print(s.nlargest(5, "Z_BPM")[cols].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
