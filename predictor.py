"""
Phase 3 - inference & cross-era comparison.

    from predictor import predict_season, all_time_leaders
    predict_season(2024)                 # top-10 table for 2023-24
    predict_season(2027, refresh=True)   # in-progress season: re-pull fresh data
    all_time_leaders(25)                 # best player-seasons ever on the common 0-100 scale

CLI:  python predictor.py 2024
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

import data_pipeline as dp
from model_trainer import DEFAULT_DATA, MODEL_DIR, prepare_features

_BUNDLE = None


def _bundle():
    global _BUNDLE
    if _BUNDLE is None:
        path = MODEL_DIR / "mvp_model.joblib"
        if not path.exists():
            raise FileNotFoundError("Run `python model_trainer.py` first to create models/mvp_model.joblib")
        _BUNDLE = joblib.load(path)
    return _BUNDLE


def _season_frame(year: int, refresh: bool) -> pd.DataFrame:
    """Rows for one season: from the processed dataset if present, else pulled (and cached) live."""
    if not refresh and Path(DEFAULT_DATA).exists():
        full = pd.read_parquet(DEFAULT_DATA)
        if (full["SEASON_ID"] == year).any():
            return full[full["SEASON_ID"] == year].copy()
    return dp.build_dataset(year, year, refresh=refresh)


def _top_drivers(contrib: np.ndarray, features: list[str], k: int = 3) -> list[str]:
    out = []
    for row in contrib:
        idx = np.argsort(row)[::-1][:k]
        out.append(", ".join(f"{features[i].removeprefix('Z_')} ({row[i]:+.3f})" for i in idx))
    return out


def predict_season(year: int, top_n: int = 10, refresh: bool = False, out_of_sample: bool = False,
                   verbose: bool = True) -> pd.DataFrame:
    """Rank MVP candidates for the season ending in `year` (2024 == 2023-24).

    Columns: MVP_Index_Score (0-100, comparable across eras), Pred_Award_Share (blended model),
    Top_3_Drivers (largest linear-model contributions, weight x era-Z, in log-odds units).
    out_of_sample=True uses leave-one-season-out predictions for training seasons, i.e. what the
    model would have said without ever seeing that year.
    """
    b = _bundle()
    feats, model, (lo, hi), iso = b["features"], b["model"], b["anchors"], b["calibrator"]

    df = prepare_features(_season_frame(year, refresh))
    pool = df[df["ELIGIBLE_NOLABEL"]].reset_index(drop=True)
    if pool.empty:
        raise ValueError(f"No eligible players for {year}")
    X = pool[feats].to_numpy()

    share = model.predict(X)
    if out_of_sample:
        loso = pd.read_csv(MODEL_DIR / "loso_predictions.csv")
        loso = loso[loso["SEASON_ID"] == year].set_index("PLAYER_ID")["BLEND"]
        if len(loso):
            share = pool["PLAYER_ID"].map(loso).fillna(pd.Series(share)).to_numpy()
    pool["Pred_Award_Share"] = iso.predict(share)
    pool["MVP_Index_Score"] = (100 * (share - lo) / (hi - lo)).clip(0, 100)

    contrib = X * model.A.coef_  # per-feature contribution to the linear (explainer) score (log-odds units)
    pool["Top_3_Drivers"] = _top_drivers(contrib, feats)

    pool = pool.sort_values("MVP_Index_Score", ascending=False).reset_index(drop=True)
    pool.insert(0, "Rank", pool.index + 1)
    cols = ["Rank", "PLAYER", "TEAM", "MVP_Index_Score", "Pred_Award_Share", "Top_3_Drivers"]
    if year in set(b.get("train_seasons", [])) or pool["MVP_SHARE"].max() > 0:
        pool["Actual_Share"] = pool["MVP_SHARE"]
        cols.insert(5, "Actual_Share")
    table = pool[cols].head(top_n).copy()
    table["MVP_Index_Score"] = table["MVP_Index_Score"].round(1)
    table["Pred_Award_Share"] = table["Pred_Award_Share"].round(3)
    if verbose:
        pd.set_option("display.width", 220)
        pd.set_option("display.max_colwidth", 70)
        print(f"\nMVP Index - {dp.season_label(year)} (top {top_n} of {len(pool)} eligible players)")
        if pool["MVP_SHARE"].max() > 0 and not out_of_sample:
            print("note: this season was in the training data (in-sample); use out_of_sample=True for a blind prediction")
        print(table.to_string(index=False))
    return table


def all_time_leaders(n: int = 25) -> pd.DataFrame:
    """Best player-seasons on the common 0-100 scale, using out-of-fold (blind) scores."""
    lo, hi = _bundle()["anchors"]
    d = pd.read_csv(MODEL_DIR / "loso_predictions.csv")
    d = d[d["ELIGIBLE_NOLABEL"]].copy()
    d["MVP_Index_Score"] = (100 * (d["BLEND"] - lo) / (hi - lo)).clip(0, 100).round(1)
    d["Season"] = d["SEASON_ID"].map(dp.season_label)
    out = d.sort_values("MVP_Index_Score", ascending=False).head(n)
    out = out[["Season", "PLAYER", "MVP_Index_Score", "MVP_SHARE"]].reset_index(drop=True)
    print(out.to_string(index=False))
    return out


if __name__ == "__main__":
    predict_season(int(sys.argv[1]) if len(sys.argv) > 1 else 2024)
