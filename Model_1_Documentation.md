# NBA MVP Index - Model 1 Documentation

Trained on 8,709 player-seasons from 47 seasons (1979-80 to 2025-26).
Season convention: `2024` means the 2023-24 season.

## 1. Headline result - read this first

Leave-One-Season-Out cross-validation (each season is predicted by models that never saw it):

| Model | Winner correct | Winner in top 3 | Top-5 overlap | Spearman (vote-getters) |
|---|---:|---:|---:|---:|
| A: linear only | 68.1% | 95.7% | 74.5% | 0.781 |
| B: XGBoost only | 72.3% | 95.7% | 76.2% | 0.798 |
| **Blend (final)** | 76.6% | 95.7% | 76.2% | 0.795 |

The blend picks the actual MVP in **76.6%** of seasons, i.e. it misses in **23.4%**.
**That does not meet the 20% miss-rate target set for this project.** Three modeling variants
were tried (plain Ridge on shares, candidate-pool restriction and share transforms, a within-season
conditional logit blended with XGBoost); all landed between roughly 66% and 77% winner accuracy.
Differences of one season (2.1 points) are noise, and the grid is selected on the same 47 seasons
used to report it, so the figure above is, if anything, slightly optimistic. Remaining misses are mostly voting-narrative
cases that box-score-derived features cannot see:

| Season | Actual MVP | Model's #1 |
|---|---|---|
| 1993 | Charles Barkley | Michael Jordan |
| 1994 | Hakeem Olajuwon | David Robinson |
| 1997 | Karl Malone | Michael Jordan |
| 1999 | Karl Malone | Shaquille O'Neal |
| 2001 | Allen Iverson | Shaquille O'Neal |
| 2005 | Steve Nash | Dirk Nowitzki |
| 2006 | Steve Nash | LeBron James |
| 2008 | Kobe Bryant | LeBron James |
| 2011 | Derrick Rose | LeBron James |
| 2022 | Nikola Jokić | Giannis Antetokounmpo |
| 2023 | Joel Embiid | Nikola Jokić |

The true MVP is in the model's top 3 in 95.7% of seasons.

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

**Model A - linear explainer.** An L2-regularized conditional logit (multinomial logistic regression, penalty 0.03).
Within each season, a player's chance of winning is a softmax over the linear score `s = sum_j w_j * Z_j`, fit against
that season's normalized vote shares. This replaced a plain Ridge on shares because most rows have share 0, which made
the ridge weights unstable (BPM and minutes came out negative) and its winner accuracy was only 47%.

**Model B - XGBoost** (depth 3, 300 trees, learning rate 0.05) on sqrt(share), to capture interactions
such as high usage *and* high efficiency.

**Blend.** Each model's raw output is standardized with global (all-season) constants, so scores remain comparable across eras:

```
A' = (s - 0.7639) / 2.4759                 where s = sum_j w_j * Z_j      (weights in section 4)
B' = (XGB(Z) - 0.0238) / 0.1065
Blend = 0.25 * A' + 0.75 * B'

MVP_Index_Score = clip( 100 * (Blend - (-0.6577)) / (8.2042 - (-0.6577)), 0, 100 )
Pred_Award_Share = IsotonicCalibration(Blend)          # monotone map fit on out-of-fold predictions
```

Index anchors: **0** = 1st percentile of eligible player-seasons; **100** = the highest out-of-fold score of any
player-season since 1980 (Michael Jordan, 1992-93). Scores above or below are clipped.
Because XGBoost carries 75% of the blend, **the linear weights below explain the model's structure but not all of its
output.** Also, the index is anchored to MVP *voting*, which saturates near 1.0, so very dominant seasons are compressed at the top.

## 4. Linear weights (Model A)

Weight = change in log-odds of winning the MVP per +1 SD (era-adjusted) in that stat, holding the others fixed.
Many stats are strongly correlated (PTS/USG/PER/WS/VORP/BPM all measure overlapping things), so **individual weights
should not be read as isolated "worth"**: e.g. the small or negative VORP/BPM weights do not mean those stats don't matter,
only that WS, PER and scoring already carry the same information. Team win % is the clearest independent signal.

| Feature (era Z-score) | Weight | % of total absolute weight |
|---|---:|---:|
| `Z_TEAM_WIN_PCT` | +0.8773 | 20.5% |
| `Z_USG_PCT` | +0.4044 | 9.4% |
| `Z_PTS` | +0.3945 | 9.2% |
| `Z_TOV` | +0.3386 | 7.9% |
| `Z_PER` | +0.2974 | 6.9% |
| `Z_WS` | +0.2863 | 6.7% |
| `Z_WS_48` | +0.2718 | 6.4% |
| `Z_MPG` | +0.2682 | 6.3% |
| `Z_AST` | +0.2287 | 5.3% |
| `Z_REB` | +0.1755 | 4.1% |
| `Z_TS_PCT` | +0.1630 | 3.8% |
| `Z_GP_PCT` | +0.1588 | 3.7% |
| `Z_BLK` | +0.1227 | 2.9% |
| `Z_BPM` | +0.0943 | 2.2% |
| `Z_STL` | -0.0177 | 0.4% |
| `Z_VORP` | -0.0201 | 0.5% |
| `Z_CARRY_PROXY` | -0.1613 | 3.8% |

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
