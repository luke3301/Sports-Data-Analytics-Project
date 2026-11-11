"""
Live ROY and DPOY predictions for the current season, from the trained award models.

  ROY   Model 1 = roy_traditional  (who the voters will pick: scoring, minutes, games, draft slot)
        Model 2 = roy_combined     (traditional + impact: adds BPM and team win %)
  DPOY  Model 1 = dpoy_traditional (who the voters will pick: reputation, center, top-5 defense, BLK/STL/TRB)
        Model 2 = dpoy_impact      (advanced impact: DBPM, DWS, BLK%, STL%, DRB%)

The current season's bbref pages (advanced, per-game, rookies, team ratings) are re-downloaded each
run; draft history and last season's award votes come from the awards data layer (awards_data.py).
Features and candidate pools are built by the same helpers used in training (award_trainer).

Usage:
    python award_inference.py            # print today's ROY and DPOY races (2026-27)
    python award_inference.py --no-refresh
"""
from __future__ import annotations

import argparse

import joblib
import numpy as np
import pandas as pd

import awards_data as ad
import data_pipeline as dp
import model_trainer  # noqa: F401 - award model bundles unpickle model_trainer.Blend
from award_trainer import AWARDS_DATA, OUT_ROOT, SPECS, add_dpoy_features, add_roy_features

CURRENT_SEASON = 2027
AWARD_MODELS = {
    "roy": ("roy_traditional", "roy_combined"),
    "dpoy": ("dpoy_traditional", "dpoy_impact"),
}


def build_live_frame(season: int, refresh: bool = True) -> pd.DataFrame:
    """One row per player for `season`, with the same columns as advanced_full.parquet."""
    adv = ad.parse_advanced(season, ad.fetch_html("advanced", season, refresh))
    adv = adv.merge(ad.parse_per_game(season, ad.fetch_html("per_game", season, refresh)),
                    on=["season_id", "bbref_id"], how="left")

    ratings = ad.parse_ratings(season, ad.fetch_html("ratings", season, refresh))
    if ratings["team_drtg"].isna().any():
        ratings = ad.fill_ratings_from_league(ratings, ad.fetch_html("league", season, refresh))
    ratings = ad.add_relative_ratings(ratings)
    # Mid-season "schedule length" = most games any team has played so far
    adv["season_games"] = int((ratings["team_wins"] + ratings["team_losses"]).max())
    adv = adv.merge(ratings.drop(columns=["team_name"]), on=["season_id", "team"], how="left")
    adv["top5_team_defense"] = adv["team_drtg_rank"] <= 5
    adv["is_center"] = adv["pos"] == "C"

    drafts = pd.read_parquet(AWARDS_DATA / "drafts.parquet")
    last_draft = drafts.sort_values("draft_year").drop_duplicates("bbref_id", keep="last")
    adv = adv.merge(last_draft[["bbref_id", "draft_year", "draft_pick"]], on="bbref_id", how="left")
    adv["undrafted"] = adv["draft_pick"].isna()

    adv = ad.add_prev_season_shares(adv, pd.read_parquet(AWARDS_DATA / "award_votes.parquet"))
    rookies = set(ad.parse_rookies(season, ad.fetch_html("rookies", season, refresh))["bbref_id"])
    adv["is_rookie"] = adv["bbref_id"].isin(rookies)
    return adv


def _score(df: pd.DataFrame, spec_key: str, prefix: str) -> pd.DataFrame:
    """Add <prefix>_score (0-100 index), <prefix>_share (calibrated vote share), <prefix>_rank."""
    b = joblib.load(OUT_ROOT / SPECS[spec_key].name.lower() / "model.joblib")
    blend = b["model"].predict(df[b["features"]].to_numpy())
    lo, hi = b["anchors"]
    df[f"{prefix}_score"] = np.clip(100 * (blend - lo) / (hi - lo), 0, 100)
    df[f"{prefix}_share"] = b["calibrator"].predict(blend)
    df[f"{prefix}_rank"] = pd.Series(blend, index=df.index).rank(ascending=False, method="first").astype(int)
    return df


def predict_award(award: str, live: pd.DataFrame) -> pd.DataFrame:
    """Eligible candidates for `award`, scored and ranked by both models (sorted by Model 1)."""
    if award == "roy":
        df = add_roy_features(live[live["is_rookie"]])
    else:
        df = add_dpoy_features(live)
    m1, m2 = AWARD_MODELS[award]
    features = sorted(set(SPECS[m1].features) | set(SPECS[m2].features))
    df = df[df["in_eval_pool"]].dropna(subset=features).copy()
    if df.empty:
        return df
    df = _score(df, m1, "m1")
    df = _score(df, m2, "m2")
    return df.sort_values("m1_rank").reset_index(drop=True)


def run_award_predictions(season: int = CURRENT_SEASON, refresh: bool = True) -> dict[str, pd.DataFrame]:
    live = build_live_frame(season, refresh)
    return {award: predict_award(award, live) for award in AWARD_MODELS}


ROY_COLS = ["m1_rank", "player", "team", "m1_score", "m1_share", "m2_rank", "m2_share",
            "pts_per_g", "mp_per_g", "games", "ts_pct", "bpm", "draft_pick"]
DPOY_COLS = ["m1_rank", "player", "team", "pos", "m1_score", "m1_share", "m2_rank", "m2_share",
             "blk_per_g", "stl_per_g", "trb_per_g", "dbpm", "dws", "team_drtg_rank", "prev_dpoy_share"]


def print_races(results: dict[str, pd.DataFrame], top: int = 10) -> None:
    pd.set_option("display.width", 250)
    for award, cols in (("roy", ROY_COLS), ("dpoy", DPOY_COLS)):
        df = results[award]
        print(f"\n{award.upper()} race - {len(df)} eligible candidates (Model 1 = voter model, Model 2 = "
              f"{'combined' if award == 'roy' else 'impact'} model):")
        if len(df):
            print(df.head(top)[cols].round(3).to_string(index=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, default=CURRENT_SEASON)
    ap.add_argument("--no-refresh", action="store_true", help="use cached bbref pages")
    a = ap.parse_args()
    print_races(run_award_predictions(a.season, refresh=not a.no_refresh))


if __name__ == "__main__":
    main()
