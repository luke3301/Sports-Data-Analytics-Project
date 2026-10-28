"""
Fix the DARKO DPM merge and retrain Model 2.

The notebook merge keyed DARKO on `name.lower()` with every non a-z character deleted, so accented
names lost letters ("Nikola Jokić" -> "nikola joki") and never matched DARKO's ASCII spelling
("nikola jokic"). Those players were filled with DPM = 0. This script:

  1. Re-merges DPM for 2014-2026 from data/raw/darko_<season>.csv using DARKO's NBA ID when the
     file has one, else data_pipeline.normalize_name (accent-folding, suffix/punctuation-insensitive).
  2. Removes duplicate (SEASON_ID, PLAYER_ID) rows created by the notebook's on/off merge for traded
     players: non-candidate copies are identical and dropped; for candidates, on/off is re-pulled from
     the player's listed team (TEAM_ID), the same rule the fixed notebook merge uses.
  3. Rewrites data/processed/model2_final_features.parquet (first original backed up as .bak).
  4. Re-evaluates RF + XGBoost + ensemble on the same split (train < 2024, test >= 2024),
     refits on all seasons and re-saves models/model2_ensemble.joblib (previous version backed up).

Usage:  python rebuild_model2.py [--dry-run]
"""
from __future__ import annotations

import argparse
import shutil
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error
from nba_api.stats.endpoints import teamplayeronoffsummary
from xgboost import XGBRegressor

import data_pipeline as dp
from model_trainer import MODEL_DIR

FEATURES_PATH = dp.PROC_DIR / "model2_final_features.parquet"
BUNDLE_PATH = MODEL_DIR / "model2_ensemble.joblib"
SEASONS = range(2014, 2027)
FEATURES = [
    "Z_PTS", "Z_REB", "Z_AST", "Z_TS_PCT", "Z_USG_PCT",
    "Z_BPM", "Z_VORP", "Z_WS", "Z_WS_48", "Z_TEAM_WIN_PCT", "Z_CARRY_PROXY",
    "Z_DPM", "on_off_net_rtg",
]
TARGET = "MVP_SHARE"

# Our normalized name -> DARKO's normalized name, for players listed under a different name
NAME_ALIASES = {
    "enes freedom": "enes kanter",
    "nic claxton": "nicolas claxton",
    "kj martin": "kenyon martin",
    "alex sarr": "alexandre sarr",
    "bub carrington": "carlton carrington",
}


# --------------------------------------------------------------------------- 1. corrected merge
def load_darko(season_id: int) -> pd.DataFrame:
    d = pd.read_csv(dp.RAW_DIR / f"darko_{season_id}.csv", encoding="utf-8-sig")
    d["DPM"] = pd.to_numeric(d["DPM"].astype(str).str.replace("+", "", regex=False), errors="coerce")
    d["NAME_KEY"] = d["Player"].map(dp.normalize_name)
    return d


def merge_darko(df: pd.DataFrame) -> pd.DataFrame:
    """Replace DPM with a correctly matched value: NBA ID first (if the file has it),
    then accent-folded name within the same season. Unmatched players are filled with 0."""
    df = df.drop(columns=["DPM"], errors="ignore").copy()
    df["DPM"] = np.nan
    for sid in SEASONS:
        d = load_darko(sid)
        rows = df["SEASON_ID"] == sid
        if "NBA ID" in d.columns:
            by_id = d.dropna(subset=["NBA ID"]).assign(ID=lambda x: x["NBA ID"].astype(int).astype(str))
            df.loc[rows, "DPM"] = df.loc[rows, "PLAYER_ID"].astype(str).map(
                by_id.drop_duplicates("ID").set_index("ID")["DPM"])
        dupes = d["NAME_KEY"].duplicated(keep=False)
        by_name = d[~dupes].set_index("NAME_KEY")["DPM"]  # ambiguous names are left unmatched
        keys = df.loc[rows, "NAME_KEY"].replace(NAME_ALIASES)
        df.loc[rows, "DPM"] = df.loc[rows, "DPM"].fillna(keys.map(by_name))
    return df


def merge_report(old: pd.DataFrame, new: pd.DataFrame) -> None:
    elig = new["ELIGIBLE"] & new["HAS_ADV"]
    print(f"Matched DPM: {new['DPM'].notna().sum()} of {len(new)} rows "
          f"({new.loc[elig, 'DPM'].notna().mean():.1%} of eligible, "
          f"{new.loc[new[TARGET] > 0, 'DPM'].notna().mean():.1%} of MVP vote-getters)")
    miss = new[elig & new["DPM"].isna()]
    if len(miss):
        print(f"Still unmatched among eligible ({len(miss)}):",
              ", ".join(f"{p} ({s})" for p, s in miss[["PLAYER", "SEASON_ID"]].head(25).values))

    cmp = old[["SEASON_ID", "PLAYER_ID", "PLAYER", "DPM"]].merge(
        new[["SEASON_ID", "PLAYER_ID", "DPM"]], on=["SEASON_ID", "PLAYER_ID"], suffixes=("_OLD", "_NEW"))
    fixed = cmp[(cmp["DPM_OLD"] == 0) & cmp["DPM_NEW"].notna() & (cmp["DPM_NEW"] != 0)]
    print(f"Rows corrected from a false 0: {len(fixed)}")
    stars = cmp[cmp["PLAYER"].isin(["Nikola Jokić", "Luka Dončić", "Giannis Antetokounmpo",
                                     "Shai Gilgeous-Alexander", "Joel Embiid"])
                & cmp["SEASON_ID"].isin([2022, 2023, 2024, 2025, 2026])]
    print(stars.pivot_table(index="PLAYER", columns="SEASON_ID", values=["DPM_OLD", "DPM_NEW"]).round(1).to_string())


# --------------------------------------------------------------------------- 2. traded-player duplicates
def listed_team_on_off(season_id: int, team_id: int, player_id: str) -> float:
    res = dp._retry(lambda: teamplayeronoffsummary.TeamPlayerOnOffSummary(
        team_id=team_id, season=dp.season_label(season_id),
        measure_type_detailed_defense="Advanced", timeout=60).get_data_frames(),
        f"on/off {season_id} team {team_id}")
    on, off = res[1], res[2]
    on = on[on["VS_PLAYER_ID"].astype(str) == player_id]["NET_RATING"]
    off = off[off["VS_PLAYER_ID"].astype(str) == player_id]["NET_RATING"]
    time.sleep(2)
    return float(on.iloc[0] - off.iloc[0]) if len(on) and len(off) else 0.0


def dedupe_traded(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse duplicate player-seasons to one row; candidates get their listed team's on/off."""
    key = ["SEASON_ID", "PLAYER_ID"]
    dup = df.duplicated(key, keep=False)
    if not dup.any():
        print("No duplicate player-seasons.")
        return df
    others = df.columns.difference(["on_off_net_rtg"]).tolist()
    assert not df[dup].drop_duplicates(others).duplicated(key).any(), "duplicates differ beyond on/off"

    out = df.drop_duplicates(key, keep="first").copy()
    fix = out[out.set_index(key).index.isin(df[dup].set_index(key).index) & out["is_candidate"]]
    for i, r in fix.iterrows():
        val = listed_team_on_off(int(r["SEASON_ID"]), int(r["TEAM_ID"]), str(r["PLAYER_ID"]))
        print(f"  {r['PLAYER']} ({r['SEASON_ID']}, {r['TEAM']}): on/off {val:+.1f}  "
              f"(copies had {sorted(df.loc[dup & (df['PLAYER_ID'] == r['PLAYER_ID']) & (df['SEASON_ID'] == r['SEASON_ID']), 'on_off_net_rtg'])})")
        out.loc[i, "on_off_net_rtg"] = val
    print(f"Removed {len(df) - len(out)} duplicate rows ({len(df)} -> {len(out)}); "
          f"re-pulled on/off for {len(fix)} traded candidates.")
    return out.reset_index(drop=True)


# --------------------------------------------------------------------------- 3. retrain
def add_z_dpm(df: pd.DataFrame) -> pd.DataFrame:
    pool = df[df["IN_REF_POOL"] & df["HAS_ADV"]].groupby("SEASON_ID")["DPM"]
    df["Z_DPM"] = (df["DPM"] - df["SEASON_ID"].map(pool.mean())) / df["SEASON_ID"].map(pool.std(ddof=0))
    return df


def make_models():
    rf = RandomForestRegressor(n_estimators=500, min_samples_leaf=5, n_jobs=-1, random_state=0)
    xgb = XGBRegressor(n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.8,
                       colsample_bytree=0.8, min_child_weight=5, random_state=0)
    return rf, xgb


def evaluate(df: pd.DataFrame) -> pd.DataFrame:
    data = df[df["HAS_ADV"]].dropna(subset=FEATURES).reset_index(drop=True)
    train, test = data[data["SEASON_ID"] < 2024], data[data["SEASON_ID"] >= 2024].copy()
    rf, xgb = make_models()
    rf.fit(train[FEATURES], train[TARGET])
    xgb.fit(train[FEATURES], train[TARGET])
    test["PRED_RF"] = np.clip(rf.predict(test[FEATURES]), 0, 1)
    test["PRED_XGB"] = np.clip(xgb.predict(test[FEATURES]), 0, 1)
    test["PRED_ENS"] = np.clip((test["PRED_RF"] + test["PRED_XGB"]) / 2, 0, 1)
    eligible = test[(test["MPG"] >= 20) & (test["GP"] >= test["MIN_GAMES_REQ"])]

    rows = []
    for col, name in [("PRED_RF", "RandomForest"), ("PRED_XGB", "XGBoost"), ("PRED_ENS", "Ensemble")]:
        hits = overlap = zero_vote = 0
        for _, s in eligible.groupby("SEASON_ID"):
            top5 = s.nlargest(5, col)
            hits += top5.iloc[0]["PLAYER_ID"] == s.loc[s[TARGET].idxmax(), "PLAYER_ID"]
            overlap += len(set(top5["PLAYER_ID"]) & set(s.nlargest(5, TARGET)["PLAYER_ID"]))
            zero_vote += (top5[TARGET] == 0).sum()
        rows.append({"model": name,
                     "test_rmse_all": mean_squared_error(test[TARGET], test[col]) ** 0.5,
                     "test_rmse_eligible": mean_squared_error(eligible[TARGET], eligible[col]) ** 0.5,
                     "winners_correct": f"{hits}/3", "top5_overlap": f"{overlap}/15",
                     "zero_vote_in_top5": zero_vote})

    for _, s in eligible.groupby("SEASON_ID"):
        print(f"\n{s['SEASON'].iloc[0]}  (actual MVP: {s.loc[s[TARGET].idxmax(), 'PLAYER']})")
        print(s.nlargest(5, "PRED_ENS")[["PLAYER", "TEAM", "DPM", "PRED_RF", "PRED_XGB", "PRED_ENS", TARGET]]
              .round(3).to_string(index=False))
    return pd.DataFrame(rows).set_index("model").round(4)


def _backup_once(path, suffix):
    """Keep the first pre-fix version: an existing backup is never overwritten."""
    bak = path.with_suffix(suffix)
    if not bak.exists():
        shutil.copy2(path, bak)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report and evaluate, but don't overwrite files")
    a = ap.parse_args()

    old = pd.read_parquet(FEATURES_PATH)
    old = dedupe_traded(old)
    new = merge_darko(old)
    merge_report(old, new)
    new["DPM"] = new["DPM"].fillna(0)  # same fill rule as before, now only for genuinely missing players
    new = add_z_dpm(new)

    old_bundle = joblib.load(BUNDLE_PATH)
    print("\nBefore (currently saved bundle):")
    print(pd.DataFrame(old_bundle["eval_metrics_2024_2026"]).set_index("model").to_string())
    summary = evaluate(new)
    print("\nAfter (corrected DPM, deduplicated):")
    print(summary.to_string())

    if a.dry_run:
        print("\n--dry-run: nothing written.")
        return

    _backup_once(FEATURES_PATH, ".parquet.bak")
    new.drop(columns=["Z_DPM"]).to_parquet(FEATURES_PATH, index=False)  # Z_DPM is derived at train time

    data = new[new["HAS_ADV"]].dropna(subset=FEATURES).reset_index(drop=True)
    rf, xgb = make_models()
    rf.fit(data[FEATURES], data[TARGET])
    xgb.fit(data[FEATURES], data[TARGET])
    _backup_once(BUNDLE_PATH, ".joblib.bak")
    joblib.dump({
        "rf": rf, "xgb": xgb, "features": FEATURES, "target": TARGET,
        "train_seasons": sorted(data["SEASON_ID"].unique().tolist()),
        "eval_metrics_2024_2026": summary.reset_index().to_dict("records"),
        "notes": "Prediction = clip((rf.predict(X) + xgb.predict(X)) / 2, 0, 1). "
                 "Z_DPM = DPM Z-scored per season against IN_REF_POOL & HAS_ADV players. "
                 "DPM merged by NBA ID, else data_pipeline.normalize_name (accent-folded). "
                 "One row per (SEASON_ID, PLAYER_ID); traded candidates use their listed team's on/off.",
    }, BUNDLE_PATH)
    print(f"\nWrote {FEATURES_PATH} ({len(new)} rows) and {BUNDLE_PATH} (backups: *.bak)")


if __name__ == "__main__":
    main()
