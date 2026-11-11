"""
Naive baselines for award models: a one-line rule each model must beat to be worth shipping.

Each baseline ranks the same candidate pool the models are evaluated on, using a single stat, and is
scored with award_trainer.season_metrics (same metrics, same co-winner handling). Trained models are
scored from their out-of-fold predictions (models/awards/<spec>/loso_predictions.csv) restricted to the
SAME seasons as the baseline frame - so a 2014+ comparison judges full-history models on 2014+ only.

Usage:
    python award_baselines.py roy
    python award_baselines.py dpoy
    python award_baselines.py roy_modern      # 2014-2026 only, incl. the DARKO model
    python award_baselines.py dpoy_modern     # 2014-2026 only, incl. the DARKO model
"""
from __future__ import annotations

import argparse

import pandas as pd

from award_trainer import OUT_ROOT, SPECS, season_metrics

# award -> (loader spec key, [(baseline name, column to rank by)], [trained spec keys to compare])
BASELINES = {
    "roy": ("roy_traditional", [("Highest-scoring rookie wins", "pts_per_g")],
            ["roy_traditional", "roy_impact", "roy_combined"]),
    "roy_modern": ("roy_modern_darko",
                   [("Highest-scoring rookie wins", "pts_per_g"), ("Highest DARKO DPM wins", "darko_dpm")],
                   ["roy_traditional", "roy_impact", "roy_combined", "roy_modern_darko"]),
    "dpoy": ("dpoy", [("Highest defensive win shares wins", "dws"), ("Most blocks per game wins", "blk_per_g")],
             ["dpoy", "dpoy_traditional", "dpoy_impact"]),
    "dpoy_modern": ("dpoy_modern_darko",
                    [("Highest defensive win shares wins", "dws"), ("Most blocks per game wins", "blk_per_g"),
                     ("Highest DARKO DDPM wins", "darko_ddpm")],
                    ["dpoy_traditional", "dpoy_impact", "dpoy_modern_darko"]),
}
METRICS = ["winner_acc", "winner_in_top3", "top5_overlap", "voter_spearman"]


def compare(award: str) -> pd.DataFrame:
    loader_key, rules, models = BASELINES[award]
    df = SPECS[loader_key].load()
    rows, misses = [], {}
    for name, col in rules:
        m = season_metrics(df.dropna(subset=[col]), col)
        rows.append({"model": f"Baseline: {name}", **{k: m[k] for k in METRICS}})
        misses[name] = m["misses"]
    seasons = set(df["season_id"])
    for key in models:
        path = OUT_ROOT / SPECS[key].name.lower() / "loso_predictions.csv"
        if not path.exists():
            print(f"(skipping {key}: run `python award_trainer.py {key}` first)")
            continue
        preds = pd.read_csv(path, dtype={"player_id": str})
        m = season_metrics(preds[preds["season_id"].isin(seasons)], "BLEND")
        rows.append({"model": f"{SPECS[key].name} (LOSO)", **{k: m[k] for k in METRICS}})
        misses[SPECS[key].name] = m["misses"]

    table = pd.DataFrame(rows).set_index("model")
    print(f"{award.upper()}: {df['season_id'].nunique()} seasons ({df['season_id'].min()}-{df['season_id'].max()}), "
          f"{int(df['in_eval_pool'].sum())} candidate player-seasons\n")
    print((table * [100, 100, 100, 1]).round({"winner_acc": 1, "winner_in_top3": 1, "top5_overlap": 1,
                                               "voter_spearman": 3}).to_string())
    for name, miss in misses.items():
        print(f"\n{name} misses ({len(miss)}): " + "; ".join(f"{s} {a} (picked {p})" for s, a, p in miss))
    return table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("award", choices=sorted(BASELINES))
    compare(ap.parse_args().award)


if __name__ == "__main__":
    main()
