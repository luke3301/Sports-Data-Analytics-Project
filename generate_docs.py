"""Regenerates Model_1_Documentation.md from models/ artifacts (run after model_trainer.py)."""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
M = ROOT / "models"
cv = json.load(open(M / "cv_results.json"))
w = pd.read_csv(M / "linear_weights.csv")
cfg, an, st, loso = cv["config"], cv["anchors"], cv["standardization"], cv["loso"]

def wtable():
    lines = ["| Feature | Weight | Share of total |Abs. weight|", "|---|---:|---:|", ]
    lines = ["| Feature (era Z-score) | Weight | % of total |Abs| ", "|---|---:|---:|"]
    lines = ["| Feature (era Z-score) | Weight | % of total absolute weight |", "|---|---:|---:|"]
    for _, r in w.iterrows():
        lines.append(f"| `{r.feature}` | {r.weight:+.4f} | {r.abs_share_pct:.1f}% |")
    return "\n".join(lines)

def cvtable():
    lines = ["| Model | Winner correct | Winner in top 3 | Top-5 overlap | Spearman (vote-getters) |", "|---|---:|---:|---:|---:|"]
    for k, label in [("LINEAR", "A: linear only"), ("XGB", "B: XGBoost only"), ("BLEND", "**Blend (final)**")]:
        m = loso[k]
        lines.append(f"| {label} | {m['winner_acc']:.1%} | {m['winner_in_top3']:.1%} | {m['top5_overlap']:.1%} | {m['voter_spearman']:.3f} |")
    return "\n".join(lines)

misses = "\n".join(f"| {m['season']} | {m['actual']} | {m['predicted']} |" for m in cv["misses"])
wl = cfg["w_linear"]
doc = f"""# NBA MVP Index - Model 1 Documentation

Trained on {cv['n_train_rows']:,} player-seasons from {cv['n_seasons']} seasons (1979-80 to 2025-26).
Season convention: `2024` means the 2023-24 season.

## 1. Headline result - read this first

Leave-One-Season-Out cross-validation (each season is predicted by models that never saw it):

{cvtable()}

The blend picks the actual MVP in **{1 - cv['miss_rate']:.1%}** of seasons, i.e. it misses in **{cv['miss_rate']:.1%}**.
**That does not meet the 20% miss-rate target set for this project.** Three modeling variants
were tried (plain Ridge on shares, candidate-pool restriction and share transforms, a within-season
conditional logit blended with XGBoost); all landed between roughly 66% and 77% winner accuracy.
Differences of one season (2.1 points) are noise, and the grid is selected on the same 47 seasons
used to report it, so the figure above is, if anything, slightly optimistic. Remaining misses are mostly voting-narrative
cases that box-score-derived features cannot see:

| Season | Actual MVP | Model's #1 |
|---|---|---|
{misses}

The true MVP is in the model's top 3 in {loso['BLEND']['winner_in_top3']:.1%} of seasons.

## 2. Pipeline

1. **Data** (`data_pipeline.py`): per-game stats from `nba_api` (1996-97 on) or Basketball-Reference
   (1979-80 to 1995-96); TS%, USG%, PER, WS, WS/48, BPM, VORP and MVP vote shares from Basketball-Reference;
   team win % from `nba_api` standings.
2. **Era normalization**: every stat is Z-scored within its own season against that season's rotation pool
   (>= 15 mpg and >= 40% of games). A "Z" is "standard deviations above that season's typical rotation player".
3. **Carry Proxy** = Z(USG%) x rTS%, where rTS% = TS% minus the season's rotation-pool average (in percentage points); it is then Z-scored too.
   `Z_GP_PCT` is share of the schedule played, Z-scored the same way.
4. **Eligibility**: 2023-24 onward (and all inference): >= 20 mpg and >= 65/82 of the season's games (scaled for short seasons).
   Training seasons through 2022-23: >= 20 mpg and >= 50/82 of games, **or** any MVP vote. Evaluation counts only
   players passing the label-free rule (20 mpg + games threshold), so the vote-getter exception does not flatter the accuracy numbers.
5. **Target**: MVP award share = points won / maximum points.

## 3. The model

**Model A - linear explainer.** An L2-regularized conditional logit (multinomial logistic regression, penalty {cfg['lam']}).
Within each season, a player's chance of winning is a softmax over the linear score `s = sum_j w_j * Z_j`, fit against
that season's normalized vote shares. This replaced a plain Ridge on shares because most rows have share 0, which made
the ridge weights unstable (BPM and minutes came out negative) and its winner accuracy was only 47%.

**Model B - XGBoost** (depth {cfg['depth']}, {cfg['n_est']} trees, learning rate 0.05) on sqrt(share), to capture interactions
such as high usage *and* high efficiency.

**Blend.** Each model's raw output is standardized with global (all-season) constants, so scores remain comparable across eras:

```
A' = (s - {st['mu_a']:.4f}) / {st['sd_a']:.4f}                 where s = sum_j w_j * Z_j      (weights in section 4)
B' = (XGB(Z) - {st['mu_b']:.4f}) / {st['sd_b']:.4f}
Blend = {wl} * A' + {1 - wl} * B'

MVP_Index_Score = clip( 100 * (Blend - ({an['lo']:.4f})) / ({an['hi']:.4f} - ({an['lo']:.4f})), 0, 100 )
Pred_Award_Share = IsotonicCalibration(Blend)          # monotone map fit on out-of-fold predictions
```

Index anchors: **0** = 1st percentile of eligible player-seasons; **100** = the highest out-of-fold score of any
player-season since 1980 (Michael Jordan, 1992-93). Scores above or below are clipped.
Because XGBoost carries {1 - wl:.0%} of the blend, **the linear weights below explain the model's structure but not all of its
output.** Also, the index is anchored to MVP *voting*, which saturates near 1.0, so very dominant seasons are compressed at the top.

## 4. Linear weights (Model A)

Weight = change in log-odds of winning the MVP per +1 SD (era-adjusted) in that stat, holding the others fixed.
Many stats are strongly correlated (PTS/USG/PER/WS/VORP/BPM all measure overlapping things), so **individual weights
should not be read as isolated "worth"**: e.g. the small or negative VORP/BPM weights do not mean those stats don't matter,
only that WS, PER and scoring already carry the same information. Team win % is the clearest independent signal.

{wtable()}

## 5. Using `predict_season(year)`

```python
from predictor import predict_season, all_time_leaders

predict_season(2024)                        # top-10 table for 2023-24
predict_season(2023, out_of_sample=True)    # blind prediction: scores from models that never saw 2023
predict_season(2027, refresh=True)          # in-progress season: re-pulls fresh data and ranks the league
predict_season(2024, top_n=20)
all_time_leaders(25)                        # best player-seasons ever on the common 0-100 scale (blind scores)
```

From the shell: `venv/bin/python predictor.py 2024`.

Output columns: `MVP_Index_Score` (0-100, comparable across eras), `Pred_Award_Share` (calibrated predicted share),
`Actual_Share` (when voting results exist) and `Top_3_Drivers` (the three largest `weight x Z` terms from the linear model,
in log-odds units). For training seasons, the default scores are in-sample; use `out_of_sample=True` for an honest historical check.
For an in-progress season, games-played thresholds scale with games played so far, but early-season results are noisy.

## 6. Reproducing

```
python data_pipeline.py --start 1980 --end 2026 --out data/processed/player_seasons_full.parquet
python model_trainer.py        # grid search with LOSO, writes models/
python generate_docs.py        # rewrites this file
```

Requires `brew install libomp` on macOS for XGBoost. Raw pulls are cached in `data/raw/`; use `--refresh` to re-fetch.
Basketball-Reference requests are spaced 4 seconds apart.

## 7. Known limitations

- Voting narrative (a team's story, voter fatigue, a player's moment) isn't captured; this is the main source of misses.
- A handful of eligible players lack advanced stats due to name mismatches between sources (e.g. "Clar. Weatherspoon"); they are excluded.
- Pre-1997 box-score stats come from a different source than 1997+; stat definitions agree but tiny differences are possible.
- Defense is represented only through STL, BLK, BPM/WS/VORP; there is no on/off or tracking data.
"""
(ROOT / "Model_1_Documentation.md").write_text(doc)
print("wrote Model_1_Documentation.md")
