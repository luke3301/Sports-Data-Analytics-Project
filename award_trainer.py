"""
Award-agnostic model trainer.

Every award (MVP, ROY, DPOY, ...) is an AwardSpec: a loader that returns one standard frame plus a
feature list. The engine is the same for all of them:

  Model A  within-season conditional logit (explicit linear weights)   - model_trainer.ConditionalLogit
  Model B  XGBoost on sqrt(vote share)                                  - inside model_trainer.Blend
  Blend    w * A' + (1 - w) * B' on a global scale, isotonic-calibrated to a vote share
  Valid.   leave-one-season-out (LOSO); a small grid scored on LOSO winner accuracy

Standard frame columns (one row per candidate player-season):
  season_id, player_id, player, share (vote share, 0 if no votes),
  in_eval_pool (label-free eligibility: who a prediction would rank), plus the spec's features.

Usage:
  python award_trainer.py mvp                  # grid search + final fit -> models/awards/mvp/
  python award_trainer.py mvp --regression     # Model 1's saved config; must reproduce models/cv_results.json
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.isotonic import IsotonicRegression

import model_trainer as m1  # Model 1's model classes (ConditionalLogit, Blend) and XGBoost settings

ROOT = Path(__file__).parent
OUT_ROOT = ROOT / "models" / "awards"
STANDARD = ["season_id", "player_id", "player", "share", "in_eval_pool"]

DEFAULT_GRID = dict(lam=[0.003, 0.01, 0.03], depth=[2, 3], n_est=[150, 300], w_linear=[0.25, 0.5, 0.75])


@dataclass
class AwardSpec:
    name: str
    load: Callable[[], pd.DataFrame]   # -> standard frame (STANDARD columns + features)
    features: list[str]
    description: str = ""
    grid: dict = field(default_factory=lambda: dict(DEFAULT_GRID))


# --------------------------------------------------------------------------- metrics
def season_metrics(df: pd.DataFrame, pred: str) -> dict:
    """Per-season ranking quality, averaged over seasons.

    Winners are every player with the season's top share (co-winners count: predicting either is a
    hit). Rankings use only `in_eval_pool` rows; a winner outside the pool counts as a miss.
    """
    hit1 = hit3 = 0
    top5, rhos, misses = [], [], []
    for season, s in df.groupby("season_id"):
        winners = s.loc[s["share"] == s["share"].max(), "player_id"]
        pool = s[s["in_eval_pool"]].sort_values(pred, ascending=False)
        top = pool["player_id"].head(3).tolist()
        if top and top[0] in set(winners):
            hit1 += 1
        else:
            misses.append((int(season), " & ".join(s.loc[s["player_id"].isin(winners), "player"]),
                           pool["player"].iloc[0] if len(pool) else "-"))
        hit3 += bool(set(top) & set(winners))
        true5 = set(pool.nlargest(5, "share")["player_id"])
        top5.append(len(true5 & set(pool["player_id"].head(5))) / 5)
        voted = pool[pool["share"] > 0]
        if len(voted) > 2:
            rhos.append(spearmanr(voted[pred], voted["share"])[0])
    n = df["season_id"].nunique()
    return dict(seasons=n, winner_acc=hit1 / n, winner_in_top3=hit3 / n, top5_overlap=float(np.mean(top5)),
                voter_spearman=float(np.nanmean(rhos)), misses=misses)


# --------------------------------------------------------------------------- LOSO engine
def loso_scores(df: pd.DataFrame, features: list[str], lam: float, depth: int, n_est: int):
    """Out-of-fold standardized scores of model A and model B for every row."""
    X, y, sid = df[features].to_numpy(), df["share"].to_numpy(), df["season_id"].to_numpy()
    a, b = np.zeros(len(df)), np.zeros(len(df))
    params = dict(max_depth=depth, n_estimators=n_est, **m1.XGB_BASE)
    for s in np.unique(sid):
        te = sid == s
        model = m1.Blend(lam, params, 0.5).fit(X[~te], y[~te], sid[~te])
        a[te], b[te] = model.parts(X[te])
    return a, b


def grid_search(df: pd.DataFrame, spec: AwardSpec, grid: dict) -> tuple[pd.DataFrame, dict]:
    rows, cache = [], {}
    for lam, depth, n_est in itertools.product(grid["lam"], grid["depth"], grid["n_est"]):
        a, b = loso_scores(df, spec.features, lam, depth, n_est)
        cache[(lam, depth, n_est)] = (a, b)
        for w in grid["w_linear"]:
            res = season_metrics(df.assign(P=w * a + (1 - w) * b), "P")
            rows.append(dict(lam=lam, depth=depth, n_est=n_est, w_linear=w,
                             **{k: v for k, v in res.items() if k != "misses"}))
        print(f"  {spec.name}: lam={lam} depth={depth} n={n_est} done", flush=True)
    order = ["winner_acc", "top5_overlap", "voter_spearman"]
    return pd.DataFrame(rows).sort_values(order, ascending=False).reset_index(drop=True), cache


def train(spec: AwardSpec, grid: dict | None = None, out_dir: Path | None = None) -> dict:
    """Grid-search on LOSO, report, fit the final model on all seasons and save artifacts."""
    df = spec.load()
    missing = [c for c in STANDARD + spec.features if c not in df.columns]
    if missing:
        raise ValueError(f"{spec.name} loader is missing columns {missing}")
    df = df.dropna(subset=spec.features).reset_index(drop=True)
    print(f"{spec.name}: {len(df)} candidate rows, {df['season_id'].nunique()} seasons "
          f"({df['season_id'].min()}-{df['season_id'].max()}), vote-getters {(df['share'] > 0).sum()}")

    res, cache = grid_search(df, spec, grid or spec.grid)
    best = res.iloc[0]
    cfg = dict(lam=float(best["lam"]), depth=int(best["depth"]), n_est=int(best["n_est"]),
               w_linear=float(best["w_linear"]))
    a, b = cache[(cfg["lam"], cfg["depth"], cfg["n_est"])]
    df["LINEAR"], df["XGB"] = a, b
    df["BLEND"] = cfg["w_linear"] * a + (1 - cfg["w_linear"]) * b

    summary = {name: {k: v for k, v in season_metrics(df, name).items() if k != "misses"}
               for name in ("LINEAR", "XGB", "BLEND")}
    final = season_metrics(df, "BLEND")
    print(f"\n{spec.name} selected {cfg}")
    for name, m in summary.items():
        print(f"  {name:7s} winner_acc={m['winner_acc']:.3f} top3={m['winner_in_top3']:.3f} "
              f"top5_overlap={m['top5_overlap']:.3f} voter_spearman={m['voter_spearman']:.3f}")
    print(f"  misses ({len(final['misses'])}):", "; ".join(f"{s} {act} (model: {p})" for s, act, p in final["misses"]))

    # Final model on all seasons + calibration and 0-100 anchors from out-of-fold scores
    X, y, sid = df[spec.features].to_numpy(), df["share"].to_numpy(), df["season_id"].to_numpy()
    model = m1.Blend(cfg["lam"], dict(max_depth=cfg["depth"], n_estimators=cfg["n_est"], **m1.XGB_BASE),
                     cfg["w_linear"]).fit(X, y, sid)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(df["BLEND"], y)
    pool = df["in_eval_pool"].to_numpy()
    anchors = (float(np.percentile(df.loc[pool, "BLEND"], 1)), float(df["BLEND"].max()))

    out = out_dir or OUT_ROOT / spec.name.lower()
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(dict(model=model, features=spec.features, anchors=anchors, calibrator=iso, config=cfg,
                     award=spec.name, train_seasons=sorted(int(s) for s in np.unique(sid))), out / "model.joblib")
    weights = pd.Series(model.A.coef_, index=spec.features).sort_values(ascending=False)
    weights.rename("weight").to_csv(out / "linear_weights.csv", index_label="feature")
    df[STANDARD + ["LINEAR", "XGB", "BLEND"]].to_csv(out / "loso_predictions.csv", index=False)
    res.to_csv(out / "grid_results.csv", index=False)
    results = dict(award=spec.name, config=cfg, loso=summary, misses=[list(m) for m in final["misses"]],
                   n_rows=len(df), n_seasons=int(df["season_id"].nunique()))
    json.dump(results, open(out / "cv_results.json", "w"), indent=2)
    print(f"  saved -> {out}")
    return results


# --------------------------------------------------------------------------- award specs
def load_mvp() -> pd.DataFrame:
    """Model 1's exact training data, mapped to the standard frame."""
    df = m1.load_training(m1.DEFAULT_DATA)
    return df.rename(columns={"SEASON_ID": "season_id", "PLAYER_ID": "player_id", "PLAYER": "player",
                              "MVP_SHARE": "share", "ELIGIBLE_NOLABEL": "in_eval_pool"})


SPECS: dict[str, AwardSpec] = {
    "mvp": AwardSpec("MVP", load_mvp, m1.FEATURES, "Most Valuable Player (reproduces Model 1)"),
}


# --------------------------------------------------------------------------- regression test
def regression_mvp() -> bool:
    """Train MVP with Model 1's saved hyperparameters through this engine; compare to Model 1's LOSO results."""
    saved = json.load(open(ROOT / "models" / "cv_results.json"))
    c = saved["config"]
    grid = dict(lam=[c["lam"]], depth=[c["depth"]], n_est=[c["n_est"]], w_linear=[c["w_linear"]])
    got = train(SPECS["mvp"], grid=grid, out_dir=OUT_ROOT / "mvp_regression")

    ok = True
    print("\nRegression vs Model 1 (models/cv_results.json):")
    for model in ("LINEAR", "XGB", "BLEND"):
        for metric in ("winner_acc", "winner_in_top3", "top5_overlap", "voter_spearman"):
            want, have = saved["loso"][model][metric], got["loso"][model][metric]
            same = abs(want - have) < 1e-9
            ok &= same
            print(f"  [{'OK ' if same else 'DIFF'}] {model:6s} {metric:15s} model1={want:.4f} trainer={have:.4f}")
    want_m = sorted((m["season"], m["actual"]) for m in saved["misses"])
    have_m = sorted((m[0], m[1]) for m in got["misses"])
    ok &= want_m == have_m
    print(f"  [{'OK ' if want_m == have_m else 'DIFF'}] identical missed seasons ({len(have_m)})")
    print("\nREGRESSION PASSED" if ok else "\nREGRESSION FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("award", choices=sorted(SPECS))
    ap.add_argument("--regression", action="store_true", help="MVP only: reproduce Model 1 and compare")
    a = ap.parse_args()
    if a.regression:
        if a.award != "mvp":
            raise SystemExit("--regression is only defined for mvp")
        sys.exit(0 if regression_mvp() else 1)
    train(SPECS[a.award])


if __name__ == "__main__":
    main()
