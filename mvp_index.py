"""
MVP Dominance Index: an unbounded linear score of statistical dominance (2014-2026).

    raw_dominance = X . w        (w = Ridge coef_ on Model 2's features, target MVP_SHARE)
    MVP_INDEX     = m * raw_dominance + b

Anchors: the median eligible player-season scores 35, and the average actual MVP winner scores 82.
There is no ceiling, so 90+ marks a historic season and 100+ is possible for extreme outliers.

Usage:  python mvp_index.py
Output: data/processed/historical_mvp_index.csv
        models/mvp_index_bundle.joblib  (Ridge weights, m, b - used by compare_models.py)
"""
from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

import data_pipeline as dp
from model_trainer import MODEL_DIR
from rebuild_model2 import FEATURES, FEATURES_PATH, TARGET, add_z_dpm

ALPHA = 10.0
MEDIAN_ANCHOR = 35.0   # median eligible player-season ("role player")
MVP_ANCHOR = 82.0      # average actual MVP winner
OUT_PATH = dp.PROC_DIR / "historical_mvp_index.csv"
BUNDLE_PATH = MODEL_DIR / "mvp_index_bundle.joblib"


def main():
    df = pd.read_parquet(FEATURES_PATH)
    if "Z_DPM" not in df.columns:  # the parquet stores raw DPM; Z_DPM is derived per season
        df = add_z_dpm(df)
    df = df[df["HAS_ADV"]].dropna(subset=FEATURES).reset_index(drop=True)

    # Label-free eligibility (the pipeline's ELIGIBLE flag keeps every vote-getter before 2024)
    df["ELIGIBLE"] = (df["MPG"] >= dp.MIN_MPG) & (df["GP"] >= df["MIN_GAMES_REQ"])
    df["IS_MVP"] = df[TARGET] == df.groupby("SEASON_ID")[TARGET].transform("max")

    # 1) Ridge on Model 2's exact features. Weights are per unit of each feature:
    #    per +1 SD for the Z_ features, per net-rating point for on_off_net_rtg.
    ridge = Ridge(alpha=ALPHA).fit(df[FEATURES], df[TARGET])
    w = pd.Series(ridge.coef_, index=FEATURES)

    # 2) Raw dominance = dot product of features and weights (no intercept; b absorbs any shift)
    df["RAW_DOMINANCE"] = df[FEATURES].to_numpy() @ w.to_numpy()

    # 3) Linear map through two anchor points
    r_median = df.loc[df["ELIGIBLE"], "RAW_DOMINANCE"].median()
    r_mvp = df.loc[df["IS_MVP"], "RAW_DOMINANCE"].mean()
    m = (MVP_ANCHOR - MEDIAN_ANCHOR) / (r_mvp - r_median)
    b = MEDIAN_ANCHOR - m * r_median
    df["MVP_INDEX"] = m * df["RAW_DOMINANCE"] + b  # deliberately unclipped

    print("Ridge weights (per unit of feature), largest first:")
    print(w.sort_values(ascending=False).round(4).to_string())
    print(f"\nAnchors: median eligible raw = {r_median:.4f} -> {MEDIAN_ANCHOR:.0f}; "
          f"mean MVP raw = {r_mvp:.4f} -> {MVP_ANCHOR:.0f}")
    print(f"Index = {m:.2f} * raw_dominance + {b:.2f}")
    print(f"Check: median eligible = {df.loc[df['ELIGIBLE'], 'MVP_INDEX'].median():.2f}, "
          f"mean MVP = {df.loc[df['IS_MVP'], 'MVP_INDEX'].mean():.2f}, "
          f"max = {df['MVP_INDEX'].max():.1f}, seasons >= 90: {(df['MVP_INDEX'] >= 90).sum()}, "
          f">= 100: {(df['MVP_INDEX'] >= 100).sum()}")

    # 4) All-time leaderboard among eligible player-seasons
    top = df[df["ELIGIBLE"]].nlargest(25, "MVP_INDEX").copy()
    top.insert(0, "Rank", range(1, len(top) + 1))
    top["Result"] = np.select(
        [top["IS_MVP"], top[TARGET] > 0], ["MVP", "MVP rank " + top["MVP_RANK"].fillna(0).astype(int).astype(str)],
        default="no votes")
    pd.set_option("display.width", 200)
    print("\nTop 25 MVP Dominance Index seasons, 2013-14 to 2025-26 (eligible players):")
    print(top[["Rank", "SEASON", "PLAYER", "TEAM", "MVP_INDEX", TARGET, "Result"]]
          .round({"MVP_INDEX": 1, TARGET: 3}).to_string(index=False))

    # 5) Lightweight export for the website (all players; ELIGIBLE lets the site filter)
    out = df[["SEASON_ID", "PLAYER", "MVP_INDEX", TARGET, "ELIGIBLE"]].copy()
    out["MVP_INDEX"] = out["MVP_INDEX"].round(2)
    out.sort_values(["SEASON_ID", "MVP_INDEX"], ascending=[True, False]).to_csv(OUT_PATH, index=False)
    print(f"\nSaved {len(out)} rows -> {OUT_PATH}")

    # 6) Bundle for live scoring (compare_models.py): MVP_INDEX = m * (X[features] . weights) + b
    joblib.dump({
        "ridge": ridge,
        "features": FEATURES,
        "weights": w.to_dict(),
        "m": float(m),
        "b": float(b),
        "anchors": {"median_eligible_raw": float(r_median), "median_eligible_index": MEDIAN_ANCHOR,
                    "mean_mvp_raw": float(r_mvp), "mean_mvp_index": MVP_ANCHOR},
        "train_seasons": sorted(df["SEASON_ID"].unique().tolist()),
    }, BUNDLE_PATH)
    print(f"Saved Ridge weights, m and b -> {BUNDLE_PATH}")


if __name__ == "__main__":
    main()
