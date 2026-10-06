"""
Phase 2 - dual-architecture MVP Index model.

  Model A (Explainer): L2-regularized conditional-logit (multinomial logistic) on era-Z-scored
                       features -> explicit linear weights.
  Model B (Booster):   XGBoost regressor -> interactions (e.g. usage AND efficiency).
  Blend:               w * A + (1 - w) * B  ->  predicted MVP award share
                       -> rescaled to a fixed 0-100 MVP Index.

Validation is Leave-One-Season-Out (LOSO): each season is predicted by models that never saw it.

Usage:
    python model_trainer.py [--data data/processed/player_seasons_full.parquet]
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from scipy.optimize import minimize
from sklearn.isotonic import IsotonicRegression
from xgboost import XGBRegressor

ROOT = Path(__file__).parent
MODEL_DIR = ROOT / "models"
DEFAULT_DATA = ROOT / "data" / "processed" / "player_seasons_full.parquet"

FEATURES = [
    "Z_PTS", "Z_REB", "Z_AST", "Z_STL", "Z_BLK", "Z_TOV", "Z_MPG",
    "Z_TS_PCT", "Z_USG_PCT", "Z_PER", "Z_WS", "Z_WS_48", "Z_BPM", "Z_VORP",
    "Z_TEAM_WIN_PCT", "Z_CARRY_PROXY", "Z_GP_PCT",
]


# --------------------------------------------------------------------------- features
def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    """Adds the availability feature and the label-free eligibility flag.

    Z_GP_PCT is games-played share of the season's schedule, Z-scored within the season
    against the same rotation pool the other features use.
    """
    df = df.copy()
    df["GP_PCT"] = df["GP"] / df["SEASON_GAMES"]
    pool = df[df["IN_REF_POOL"] & df["HAS_ADV"]].groupby("SEASON_ID")["GP_PCT"]
    df["Z_GP_PCT"] = (df["GP_PCT"] - df["SEASON_ID"].map(pool.mean())) / df["SEASON_ID"].map(pool.std(ddof=0))
    # Eligibility that does NOT peek at MVP votes (the pipeline's training flag keeps every vote-getter).
    df["ELIGIBLE_NOLABEL"] = (df["MPG"] >= 20) & (df["GP"] >= df["MIN_GAMES_REQ"]) & df["HAS_ADV"]
    return df


def load_training(path: Path) -> pd.DataFrame:
    df = prepare_features(pd.read_parquet(path))
    # Train on everything the pipeline marked eligible (incl. relaxed historical vote-getters).
    # Only seasons with real voting results have labels.
    labelled = df.groupby("SEASON_ID")["MVP_SHARE"].transform("max") > 0
    return df[df["ELIGIBLE"] & df["HAS_ADV"] & labelled].reset_index(drop=True)


# --------------------------------------------------------------------------- models
class ConditionalLogit:
    """Model A (Explainer): linear score s = w . Z with a within-season softmax.

    P(player i wins | season) = exp(s_i) / sum_j exp(s_j), fit against each season's normalized
    vote shares (cross-entropy) with an L2 (ridge) penalty. It is a multinomial/logistic
    regression, so every feature gets one explicit weight in the units of 'log-odds of MVP
    voting per +1 SD (era-adjusted)'. One winner per season is exactly what MVP voting is,
    which a plain regression on shares (mostly zeros) fits poorly.
    """

    def __init__(self, lam):
        self.lam = lam
        self.coef_ = None

    def fit(self, X, y, seasons):
        groups = [np.where(seasons == s)[0] for s in np.unique(seasons)]
        q = [y[g] / y[g].sum() for g in groups]
        lam, n = self.lam, len(groups)

        def f(w):
            s = X @ w
            loss, grad = 0.0, np.zeros_like(w)
            for g, qq in zip(groups, q):
                sg = s[g] - s[g].max()
                p = np.exp(sg)
                p /= p.sum()
                loss -= (qq * np.log(p + 1e-12)).sum()
                grad += X[g].T @ (p - qq)
            return loss / n + lam * w @ w, grad / n + 2 * lam * w

        self.coef_ = minimize(f, np.zeros(X.shape[1]), jac=True, method="L-BFGS-B").x
        return self

    def score(self, X):
        return X @ self.coef_


class Blend:
    """A (linear score) + B (XGBoost on sqrt(share)), each standardized on a GLOBAL scale
    (training-set mean/std, not per season) so blended scores stay comparable across eras."""

    def __init__(self, lam, xgb_params, w_linear):
        self.A = ConditionalLogit(lam)
        self.B = XGBRegressor(**xgb_params)
        self.w = w_linear
        self.stats = None  # (muA, sdA, muB, sdB), set after fit

    def fit(self, X, y, seasons):
        self.A.fit(X, y, seasons)
        self.B.fit(X, np.sqrt(y))
        a, b = self.A.score(X), self.B.predict(X)
        self.stats = (a.mean(), a.std(), b.mean(), b.std())
        return self

    def parts(self, X, stats=None):
        mu_a, sd_a, mu_b, sd_b = stats or self.stats
        return (self.A.score(X) - mu_a) / sd_a, (self.B.predict(X) - mu_b) / sd_b

    def predict(self, X):
        a, b = self.parts(X)
        return self.w * a + (1 - self.w) * b


XGB_BASE = dict(learning_rate=0.05, subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
                reg_lambda=2.0, random_state=0, n_jobs=4, verbosity=0)


# --------------------------------------------------------------------------- evaluation
def season_metrics(df: pd.DataFrame, pred_col: str) -> dict:
    """Ranking quality among label-free-eligible players of every season."""
    hit1 = hit3 = top5 = 0
    rhos, n = [], 0
    misses = []
    for sid, s in df[df["ELIGIBLE_NOLABEL"] | (df["MVP_SHARE"] >= df.groupby("SEASON_ID")["MVP_SHARE"].transform("max"))].groupby("SEASON_ID"):
        # candidate pool = label-free eligible; winner is always counted (miss if ineligible)
        pool = s[s["ELIGIBLE_NOLABEL"]]
        winner = s.loc[s["MVP_SHARE"].idxmax()]
        n += 1
        ranked = pool.sort_values(pred_col, ascending=False)
        if len(ranked) and ranked.iloc[0]["PLAYER_ID"] == winner["PLAYER_ID"]:
            hit1 += 1
        else:
            misses.append((int(sid), winner["PLAYER"], ranked.iloc[0]["PLAYER"] if len(ranked) else "-"))
        if winner["PLAYER_ID"] in set(ranked.head(3)["PLAYER_ID"]):
            hit3 += 1
        true5 = set(pool.nlargest(5, "MVP_SHARE")["PLAYER_ID"])
        top5 += len(true5 & set(ranked.head(5)["PLAYER_ID"])) / 5
        voted = pool[pool["MVP_SHARE"] > 0]
        if len(voted) > 2:
            rhos.append(spearmanr(voted[pred_col], voted["MVP_SHARE"])[0])
    return dict(seasons=n, winner_acc=hit1 / n, winner_in_top3=hit3 / n, top5_overlap=top5 / n,
                voter_spearman=float(np.nanmean(rhos)), misses=misses)


def rmse(a, b):
    return float(np.sqrt(np.mean((a - b) ** 2)))


def loso_scores(df, lam, depth, n_est):
    """Out-of-fold raw scores. Each season is scored by models trained on all OTHER seasons.
    Raw A/B scores are standardized with that fold's training statistics."""
    X, y, sid = df[FEATURES].to_numpy(), df["MVP_SHARE"].to_numpy(), df["SEASON_ID"].to_numpy()
    a, b = np.zeros(len(df)), np.zeros(len(df))
    xgb_params = dict(max_depth=depth, n_estimators=n_est, **XGB_BASE)
    for s in np.unique(sid):
        te = sid == s
        m = Blend(lam, xgb_params, 0.5).fit(X[~te], y[~te], sid[~te])
        a[te], b[te] = m.parts(X[te])
    return a, b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    args = ap.parse_args()

    df = load_training(Path(args.data))
    print(f"Training rows: {len(df)} across {df['SEASON_ID'].nunique()} seasons "
          f"({df['SEASON_ID'].min()}-{df['SEASON_ID'].max()}); vote-getters: {(df['MVP_SHARE'] > 0).sum()}")
    y, sid = df["MVP_SHARE"].to_numpy(), df["SEASON_ID"].to_numpy()

    # ---- small grid, every config scored by LOSO. A and B out-of-fold scores are cached per
    # (lam, depth, n_est); the blend weight is then a cheap sweep.
    grid_lam, grid_depth, grid_n, grid_w = [0.003, 0.01, 0.03], [2, 3], [150, 300], [0.25, 0.5, 0.75]
    rows = []
    tmp = df[["SEASON_ID", "PLAYER_ID", "PLAYER", "MVP_SHARE", "ELIGIBLE_NOLABEL"]].copy()
    cache = {}
    for lam, depth, n_est in itertools.product(grid_lam, grid_depth, grid_n):
        a, b = loso_scores(df, lam, depth, n_est)
        cache[(lam, depth, n_est)] = (a, b)
        for w in grid_w:
            tmp["P"] = w * a + (1 - w) * b
            m = season_metrics(tmp, "P")
            rows.append(dict(lam=lam, depth=depth, n_est=n_est, w_linear=w,
                             **{k: v for k, v in m.items() if k != "misses"}))
        print(f"  lam={lam} depth={depth} n={n_est} done", flush=True)
    res = pd.DataFrame(rows)
    order = ["winner_acc", "top5_overlap", "voter_spearman"]
    res = res.sort_values(order, ascending=False)
    print("\nTop 8 configurations (LOSO):")
    print(res.head(8).round(4).to_string(index=False))
    best = res.iloc[0]
    lam, depth, n_est, w = best["lam"], int(best["depth"]), int(best["n_est"]), float(best["w_linear"])
    print("\nSelected:", dict(lam=lam, depth=depth, n_est=n_est, w_linear=w))

    a, b = cache[(lam, depth, n_est)]
    tmp["LINEAR"], tmp["XGB"], tmp["BLEND"] = a, b, w * a + (1 - w) * b
    print("\n=== LOSO cross-validation (final) ===")
    summary = {}
    for name in ["LINEAR", "XGB", "BLEND"]:
        m = season_metrics(tmp, name)
        summary[name] = {k: v for k, v in m.items() if k != "misses"}
        print(f"{name:7s} winner_acc={m['winner_acc']:.3f} top3={m['winner_in_top3']:.3f} "
              f"top5_overlap={m['top5_overlap']:.3f} voter_spearman={m['voter_spearman']:.3f}")
    final = season_metrics(tmp, "BLEND")
    miss_rate = 1 - final["winner_acc"]
    print(f"\nBLEND misses the MVP in {miss_rate:.1%} of seasons (target: <= 20%). Misses:")
    for s_, actual, pred in final["misses"]:
        print(f"   {s_}: actual {actual:<26s} predicted {pred}")

    # ---- fit final models on all seasons
    X = df[FEATURES].to_numpy()
    model = Blend(lam, dict(max_depth=depth, n_estimators=n_est, **XGB_BASE), w).fit(X, y, sid)

    # Calibrate blended score -> predicted award share (monotone, from out-of-fold predictions)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(tmp["BLEND"], y)
    elig = tmp["ELIGIBLE_NOLABEL"].to_numpy()
    lo = float(np.percentile(tmp.loc[elig, "BLEND"], 1))
    hi = float(tmp["BLEND"].max())
    tmp["PRED_SHARE"] = iso.predict(tmp["BLEND"])
    tmp["MVP_INDEX"] = (100 * (tmp["BLEND"] - lo) / (hi - lo)).clip(0, 100)
    print(f"Share-calibration RMSE (OOF): {rmse(tmp['PRED_SHARE'].to_numpy(), y):.4f}")

    MODEL_DIR.mkdir(exist_ok=True)
    bundle = dict(model=model, features=FEATURES, anchors=(lo, hi), calibrator=iso,
                  train_seasons=sorted(int(x) for x in np.unique(sid)),
                  config=dict(lam=lam, depth=depth, n_est=n_est, w_linear=w))
    joblib.dump(bundle, MODEL_DIR / "mvp_model.joblib")

    coef = model.A.coef_
    weights = pd.DataFrame({"feature": FEATURES, "weight": coef})
    weights["abs_share_pct"] = 100 * weights["weight"].abs() / weights["weight"].abs().sum()
    weights = weights.sort_values("weight", ascending=False)
    weights.to_csv(MODEL_DIR / "linear_weights.csv", index=False)
    tmp.to_csv(MODEL_DIR / "loso_predictions.csv", index=False)
    mu_a, sd_a, mu_b, sd_b = model.stats
    json.dump(dict(config=bundle["config"], anchors=dict(lo=lo, hi=hi),
                   standardization=dict(mu_a=float(mu_a), sd_a=float(sd_a), mu_b=float(mu_b), sd_b=float(sd_b)),
                   loso=summary, miss_rate=miss_rate,
                   misses=[dict(season=s_, actual=a_, predicted=p) for s_, a_, p in final["misses"]],
                   n_train_rows=len(df), n_seasons=int(df["SEASON_ID"].nunique())),
              open(MODEL_DIR / "cv_results.json", "w"), indent=2)
    res.to_csv(MODEL_DIR / "grid_results.csv", index=False)

    print("\nLinear (conditional-logit) weights, per +1 SD of the era-adjusted feature:")
    print(weights.round(4).to_string(index=False))
    print(f"\nIndex anchors: 0 -> blend {lo:.4f}, 100 -> blend {hi:.4f}\nSaved models/ artifacts.")


if __name__ == "__main__":
    # Re-import under the real module name so pickled classes resolve as model_trainer.Blend
    # (not __main__.Blend) when predictor.py loads the bundle.
    import model_trainer
    model_trainer.main()
