# NBA MVP Predictor: Model 2 Documentation

Model 2 is a modern-era MVP predictor (2013-14 through 2025-26). It takes Model 1's era-normalized
box-score features, adds two impact metrics (DARKO DPM and team on/off net rating), and predicts each
player's MVP award share with an equal-weight Random Forest + XGBoost ensemble.

| | |
|---|---|
| Notebook | `model_2_development.ipynb` |
| Feature dataset | `data/processed/model2_final_features.parquet` (6,942 player-seasons, one row each, 56 columns) |
| Saved model | `models/model2_ensemble.joblib` |
| Target | `MVP_SHARE` = MVP voting points won / maximum possible points (0 to 1) |
| Season convention | `SEASON_ID` is the year the season ends (`2024` = 2023-24) |

---

## 1. Overview & Data Scope

### Seasons
2014-2026 (`SEASON_ID`), covering 13 seasons from 2013-14 through 2025-26. This is a subset of the
1980-2026 baseline built by `data_pipeline.py` for Model 1 (`data/processed/player_seasons_full.parquet`).

### Traditional and advanced stats
These come from the Model 1 pipeline:

- **Box score** (per game, from `nba_api`): points, rebounds, assists, steals, blocks, turnovers, minutes, games played.
- **Advanced** (from Basketball-Reference): TS%, USG%, PER, Win Shares, WS/48, BPM, VORP.
- **Team context:** team win percentage from `nba_api` standings.
- **Label:** MVP vote share from Basketball-Reference award pages.

### Season-relative Z-score normalization
Every stat is converted to a Z-score **within its own season**, measured against that season's
rotation pool (players with at least 15 minutes per game who appeared in at least 40% of games). A `Z_PTS` of +2.0 means
"two standard deviations above a typical rotation player *that season*". This removes pace and scoring
inflation, so 30 points per game in a slow season and in a fast season are judged on the same scale.

The **Carry Proxy** (`Z_CARRY_PROXY`) multiplies usage Z-score by relative true shooting (TS% minus the
season's rotation-pool average). It rewards players who take on a large offensive load *and* stay efficient.

### External metrics added for Model 2

**DARKO DPM** (`DPM`, normalized to `Z_DPM`)
- Daily Plus-Minus, a player-impact estimate. It was loaded from season files `data/raw/darko_2014.csv` to `darko_2026.csv`.
- **Matching** (`merge_darko` in `rebuild_model2.py`, also used by the notebook):
  1. If the DARKO file has an `NBA ID` column, match on it directly against `nba_api`'s `PLAYER_ID`. Only `darko_2027.csv` has one today.
  2. Otherwise match within the same season on `data_pipeline.normalize_name`. It folds accents instead of deleting them
     ("Nikola Jokić" → `nikola jokic`, the same as DARKO's "Nikola Jokic"), and ignores case, punctuation and Jr./Sr./II/III suffixes.
  3. A small alias map covers five players DARKO lists under another name: Enes Freedom → Enes Kanter, Nic → Nicolas Claxton,
     KJ → Kenyon Martin, Alex → Alexandre Sarr, Bub → Carlton Carrington.
- **Coverage:** 100% of eligible player-seasons and 100% of MVP vote-getters match. The one eligible miss is Mario Chalmers
  (2015-16), who isn't in that season's DARKO file.
- Players DARKO doesn't list are filled with `0` (league-average impact). That's **9.5% of all rows**, almost all deep-bench
  players. Only 2.1% of eligible player-seasons sit at exactly 0, and most of those are genuine 0.0 ratings.
- `Z_DPM` is DPM Z-scored per season against the same rotation pool as the other features.

**Team on/off net rating** (`on_off_net_rtg`)
- The team's net rating with the player on the court, minus its net rating with that player off it. It comes from `nba_api` `TeamPlayerOnOffSummary`.
- To limit API traffic, only **realistic MVP candidates** were pulled: the **top 25 players by VORP in each season** (329 player-seasons in total).
- Each request returns every player on one team, so the loop made one call per (season, team) pair containing a candidate, with a 2-second pause between calls.
- Non-candidates are filled with `0`.
- **Traded players:** the merge joins on `(SEASON_ID, PLAYER_ID, TEAM_ID)`, where `TEAM_ID` is the player's listed (latest)
  team. A traded candidate therefore gets that stint's on/off, and each player-season stays a single row.

### Final feature set (13 features)

| Group | Features |
|---|---|
| Scoring and playmaking | `Z_PTS`, `Z_REB`, `Z_AST` |
| Efficiency and load | `Z_TS_PCT`, `Z_USG_PCT`, `Z_CARRY_PROXY` |
| All-in-one impact | `Z_BPM`, `Z_VORP`, `Z_WS`, `Z_WS_48`, `Z_DPM` |
| Team context | `Z_TEAM_WIN_PCT`, `on_off_net_rtg` |

`is_candidate` (a flag for "top 25 by VORP") was tested and dropped. Its feature importance was 0.000,
because the trees already learn the same split directly from `Z_VORP`.

---

## 2. Model Architecture & Ensemble

### Models compared
All three models were trained on identical features, target, and rows. Only rows with complete
advanced stats were used.

| Model | Configuration |
|---|---|
| **Ridge regression** | `StandardScaler` + `Ridge(alpha=10)` |
| **Random Forest** | `RandomForestRegressor(n_estimators=500, min_samples_leaf=5, random_state=0)` |
| **XGBoost** | `XGBRegressor(n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8, min_child_weight=5, random_state=0)` |

### Why Ridge was dropped
MVP share is almost entirely zeros, with a few large values for the real contenders. A linear model can't
fit that shape. Ridge's top-5 predictions were squashed into a narrow 0.12-0.32 range, and it ranked Jokić
ahead of Shai Gilgeous-Alexander in both 2025 and 2026, picking only 1 of 3 winners.

### Why an equal-weight Random Forest + XGBoost ensemble
Each tree model has a different strength:
- **XGBoost** has the lower error on both measures (0.0151 vs. 0.0164 across all players, 0.0268 vs. 0.0287 on eligible players).
  It pushes hardest on the leaders, though sometimes too hard: it predicts 1.000 for SGA in 2025 against an actual 0.913.
- **Random Forest** reproduces the real top 5 better (13 of 15 players vs. 12) and pulls in fewer zero-vote players (2 vs. 3).

Their errors also differ in direction. Random Forest pulls predictions toward the average, while XGBoost
pushes harder on the leaders. Averaging the two beats both on error and keeps Random Forest's top-5 accuracy:

```python
pred = np.clip((rf.predict(X) + xgb.predict(X)) / 2, 0, 1)
```

Equal weights were used deliberately. With only three test seasons, tuning the weights would amount to
fitting noise.

---

## 3. Performance & Evaluation

### Holdout design
- **Chronological split:** train on 2014-2023 (5,176 player-seasons) and test on 2024-2026 (1,709 player-seasons). The models
  never see the test seasons during training, so the test works like predicting a season that hasn't
  been played yet.
- **Eligibility for ranking:** test-season top-5 lists include only players who meet the current award rules:
  at least 20 minutes per game and at least 65 of 82 games.

### Results on the 2024-2026 test seasons

| Model | RMSE (all players) | RMSE (eligible) | Winners correct | Top-5 overlap | Zero-vote players in top 5 |
|---|---:|---:|---:|---:|---:|
| Ridge | 0.0416 | 0.0793 | 1/3 | 11/15 | 3 |
| Random Forest | 0.0164 | 0.0287 | **3/3** | **13/15** | **2** |
| XGBoost | 0.0151 | 0.0268 | **3/3** | 12/15 | 3 |
| **Ensemble (final)** | **0.0144** | **0.0267** | **3/3** | **13/15** | **2** |

All numbers are on the **final cleaned data**: corrected DPM and one row per player-season (October 2026 rebuild, see below).

The ensemble **picked the MVP correctly in all three seasons** (Jokić in 2024, Gilgeous-Alexander in 2025
and 2026). It placed 13 of the 15 real top-5 vote-getters in its top 5, and it had the lowest RMSE on both measures.

### Effect of the data fixes
The original training data had **DPM = 0 for Nikola Jokić and Luka Dončić in every season**. The notebook's first merge deleted
accented letters, so "jokić" became "joki" and never matched DARKO's "jokic". 199 player-seasons were corrected in total.
Jokić's 2022-2026 DPM is now 5.5 to 7.5, and Dončić's is 3.3 to 5.7.

The on/off merge also **duplicated 298 player-seasons** for traded players: 6,942 player-seasons were stored as 7,240 rows.
The duplicates were collapsed, and the four traded candidates got their listed team's on/off: Domantas Sabonis, James Harden
and Tyrese Haliburton in 2021-22, and Harden in 2025-26. For example, Harden's 2021-22 is now PHI's +14.5 rather than a mix
with Brooklyn's +2.9.

| Ensemble on 2024-2026 | RMSE (all) | RMSE (eligible) | Winners | Top-5 overlap | Zero-vote in top 5 |
|---|---:|---:|---:|---:|---:|
| Original (buggy DPM, duplicates) | 0.0141 | 0.0262 | 3/3 | 13/15 | 2 |
| DPM fixed | 0.0149 | 0.0275 | 3/3 | 13/15 | 2 |
| **DPM fixed + deduplicated (current)** | 0.0144 | 0.0267 | 3/3 | 13/15 | 2 |

Winners and top-5 quality are unchanged throughout. Fixing DPM raised the error slightly, and removing the duplicates won most of it back. The old figures were partly luck: the model learned to ignore DPM when
the leading candidates often showed 0. Three test seasons can't make the RMSE difference meaningful in either direction.
For XGBoost on its own, top-5 overlap went from 12/15 to 13/15 with the DPM fix, then back to 12/15 after deduplication.
Movement of one player in either direction is within the noise of a 3-season test.

### Ensemble top 5 by season

**2023-24**: actual MVP Nikola Jokić
| Player | Predicted share | Actual share |
|---|---:|---:|
| Nikola Jokić | 0.761 | 0.935 |
| Luka Dončić | 0.481 | 0.572 |
| Giannis Antetokounmpo | 0.452 | 0.194 |
| Shai Gilgeous-Alexander | 0.368 | 0.646 |
| Jalen Brunson | 0.088 | 0.143 |

**2024-25**: actual MVP Shai Gilgeous-Alexander
| Player | Predicted share | Actual share |
|---|---:|---:|
| Shai Gilgeous-Alexander | 0.925 | 0.913 |
| Nikola Jokić | 0.699 | 0.787 |
| Giannis Antetokounmpo | 0.521 | 0.470 |
| Jayson Tatum | 0.040 | 0.311 |
| Tyrese Haliburton | 0.016 | 0.000 |

**2025-26**: actual MVP Shai Gilgeous-Alexander
| Player | Predicted share | Actual share |
|---|---:|---:|
| Shai Gilgeous-Alexander | 0.885 | 0.939 |
| Nikola Jokić | 0.689 | 0.634 |
| Kawhi Leonard | 0.111 | 0.001 |
| Jaylen Brown | 0.037 | 0.089 |
| Jalen Duren | 0.035 | 0.000 |

### How to read these results
- **The leaders are strong; the bottom of the top 5 is noisy.** The top 2-3 candidates are ranked well every season. The 4th and 5th spots
  are close to the noise floor (predicted shares of 0.02-0.11), where players with no votes can sneak in. Examples are Tyrese Haliburton
  in 2025 and Jalen Duren and Kawhi Leonard (0.001) in 2026. Both component models make this kind of mistake, so averaging
  doesn't remove it.
- **Three test seasons is a small sample.** One season is a third of the winner accuracy, and Random Forest,
  XGBoost and the ensemble differ by only one or two players. For comparison, Model 1's leave-one-season-out validation over 47 seasons
  picks the winner 76.6% of the time. Expect Model 2's long-run accuracy to be in that range rather than 100%.
- **RMSE across all players is flattered by the zero-share majority.** RMSE on eligible players and the top-5 metrics are the
  more meaningful measures.

---

## 4. Using the Saved Model

`models/model2_ensemble.joblib` was **refit on all labelled seasons (2014-2026)** after evaluation, so it
has seen the most recent voting. The test metrics above come from the models trained on seasons before 2024; the
saved refit has no held-out score of its own.

```python
import joblib
import numpy as np

b = joblib.load("models/model2_ensemble.joblib")
# b keys: rf, xgb, features, target, train_seasons, eval_metrics_2024_2026, notes

# X must contain b["features"] built exactly as in training:
#   - Z_ features from data_pipeline.py (season-relative, rotation-pool baseline)
#   - DPM merged with rebuild_model2.merge_darko (NBA ID, else accent-folded name), then
#     Z_DPM = DPM Z-scored per season against IN_REF_POOL & HAS_ADV players
#   - on_off_net_rtg for the top 25 players by VORP, 0 for everyone else
X = season_df[b["features"]]
season_df["PRED_SHARE"] = np.clip((b["rf"].predict(X) + b["xgb"].predict(X)) / 2, 0, 1)

eligible = season_df[(season_df["MPG"] >= 20) & (season_df["GP"] >= season_df["MIN_GAMES_REQ"])]
eligible.nlargest(5, "PRED_SHARE")[["PLAYER", "TEAM", "PRED_SHARE"]]
```

For the in-progress season, `compare_models.py` does all of this. It re-pulls 2026-27, merges `data/raw/darko_2027.csv` by
NBA ID, pulls on/off for the top 25 by VORP, and prints Model 1 and Model 2 side by side.

To rebuild after changing DARKO files or the merge: `venv/bin/python rebuild_model2.py --dry-run` reports the match rate and
metrics without writing anything. Without `--dry-run` it rewrites the feature parquet and the bundle, and backs up the previous
versions as `*.bak`.

**Reproducibility note:** `data/` is git-ignored, so the DARKO CSVs and the feature parquet are not in the
repository. Rebuilding Model 2 on another machine needs the DARKO files in `data/raw/darko_<year>.csv`.

---

## 5. Future Improvements

### Reducing low-vote noise at the bottom of the top 5
- **Two-stage (hurdle) model.** First, a classifier estimates P(player receives any votes). Second, a regressor
  predicts share *given* votes. The final prediction is the product of the two. This targets exactly the 4th-5th spot
  problem: zero-vote players like Tyrese Haliburton in 2025 would need to clear the "gets votes" bar first.
- **Rank-aware objective.** Train XGBoost with `XGBRanker` (`rank:pairwise` or `rank:ndcg`), grouping rows by season, so the
  model optimizes the order of candidates rather than squared error on thousands of zeros.
- **Separate missing from average.** DPM and on/off are currently filled with 0, which is indistinguishable from a genuine
  league-average value (9.5% of DPM rows are unlisted bench players filled with 0). Use NaN, which XGBoost handles natively, or add a `has_dpm` / `has_onoff` flag.
- **Pull on/off for every eligible player**, not just the top 25 by VORP. Today a player ranked 26th by VORP gets 0 even with
  a large on/off impact. The extra API cost is modest, because each call already returns the whole team.
- **Evaluate with leave-one-season-out validation over 2014-2026** instead of a single 3-season holdout. That gives 13
  test seasons instead of 3, enough to tell Random Forest, XGBoost and the ensemble apart and to tune the blend weight.
- **Rolling-origin backtests** (train through year N, predict N+1, repeat) to mimic live use.

### Handling traded players
- **On/off is currently team-specific.** The API is called with the player's *last* team (`TEAM_ID`), and the merge keys on it,
  so for a traded player only the stint with the player's final team counts (and no longer creates duplicate rows). A better approach is to call the endpoint for every team the player played for
  and combine the results, weighting each stint's on/off by minutes played.
- **Team win percentage has the same issue.** It uses the final team's record. A minutes-weighted average across stints,
  or the team's record in the games the player actually played, would be more accurate.
- **Name-based merges.** Historical DARKO files (2014-2026) have no player ID, so they still match on accent-folded names
  plus an alias map. New players with nicknames will need alias entries; `rebuild_model2.py` lists any unmatched eligible
  players. Re-downloading historical DARKO files with the `NBA ID` column would remove the name dependency entirely.
  The Basketball-Reference merge in `data_pipeline.py` is also name-based.
- **Flag mid-season trades** (`traded = 1`) so the model can learn whether voters penalize them.
  Trades are rare among real MVP candidates, so this matters more for cleanliness than for accuracy.

---

## 6. Data Fix Log

- **DARKO DPM name matching (fixed October 2026).** The original merge deleted accented letters, so Jokić, Dončić and others got
  DPM = 0. Now matched by NBA ID, else by accent-folded name plus an alias map. See "Effect of the data fixes" in section 3.
- **Traded-player duplicate rows (fixed October 2026).** The on/off merge joined on `(SEASON_ID, PLAYER_ID)` only, so 298
  player-seasons were stored twice. It now joins on `TEAM_ID` as well and asserts there are no duplicates. `rebuild_model2.py` collapsed the
  existing duplicates and re-pulled the listed team's on/off for the four traded candidates.
- **Backups:** `data/processed/model2_final_features.parquet.bak` and `models/model2_ensemble.joblib.bak` hold the original
  pre-fix versions. `rebuild_model2.py` never overwrites an existing backup.
