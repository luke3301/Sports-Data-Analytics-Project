"""
Sync MVP data to TiDB Serverless (MySQL-compatible).

Tables (created if missing):
  historical_mvp          one row per player-season from data/processed/historical_mvp_index.csv
  daily_predictions       live MVP race snapshots from compare_models.py, one row per player per day
  daily_roy_predictions   live Rookie of the Year race (rookies only), one row per rookie per day
  daily_dpoy_predictions  live Defensive Player of the Year race, one row per candidate per day
  nba_mvp_ladder          the official NBA.com Kia MVP Ladder Top 10 (insights.fetch_mvp_ladder)
The three daily tables also carry insights for the players shown on the site (insights.py):
summary (1-2 sentences), rank_change (vs the previous saved day; + = climbed) and recent_games
(JSON list of the last 3 games' box scores).
ROY and DPOY rows come from award_inference.py; player_id there is the bbref player id.

Usage:
    python db_sync.py              # create tables, replace historical_mvp with the CSV
    python db_sync.py --check      # connect and print row counts only

Connection: DATABASE_URL in .env, e.g.
    DATABASE_URL=mysql+pymysql://<user>:<password>@<host>:4000/<database>
TiDB Serverless requires TLS; if the URL has no ssl_* options, the certifi CA bundle is used.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

import certifi
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import (Boolean, Column, Date, DateTime, Double, Integer, MetaData, String, Table, Text,
                        UniqueConstraint, create_engine, delete, func, insert, inspect, select, text)
from sqlalchemy.engine import Engine, make_url

ROOT = Path(__file__).parent
HISTORICAL_CSV = ROOT / "data" / "processed" / "historical_mvp_index.csv"
CHUNK = 1000

metadata = MetaData()

historical_mvp = Table(
    "historical_mvp", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("season_id", Integer, nullable=False, index=True),   # season end year: 2024 = 2023-24
    Column("player", String(64), nullable=False),
    Column("mvp_index", Double, nullable=False),
    Column("mvp_share", Double, nullable=False),
    Column("eligible", Boolean, nullable=False),
    UniqueConstraint("season_id", "player", name="uq_historical_season_player"),
    mysql_charset="utf8mb4",
)

daily_predictions = Table(
    "daily_predictions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("prediction_date", Date, nullable=False, index=True),
    Column("season_id", Integer, nullable=False),
    Column("player_id", String(32), nullable=False),
    Column("player", String(64), nullable=False),
    Column("team", String(8)),
    Column("model1_rank", Integer),
    Column("model1_score", Double),    # Model 1 MVP Index Score (0-100)
    Column("model1_share", Double),    # Model 1 predicted award share
    Column("model2_rank", Integer),
    Column("model2_share", Double),    # Model 2 ensemble predicted award share
    Column("mvp_index", Double),       # unbounded MVP Dominance Index
    # Box-score context for the dashboard (season to date, per game)
    Column("pts", Double),
    Column("mpg", Double),
    Column("ts_pct", Double),          # true shooting, as a fraction (0.62 = 62%)
    Column("bpm", Double),
    Column("vorp", Double),
    Column("reb", Double),             # season per-game rebounds
    Column("ast", Double),             # season per-game assists
    Column("is_rookie", Boolean),
    Column("summary", Text),
    Column("rank_change", Integer),
    Column("recent_games", Text),      # JSON
    Column("created_at", DateTime, server_default=text("CURRENT_TIMESTAMP")),
    UniqueConstraint("prediction_date", "season_id", "player_id", name="uq_daily_date_season_player"),
    mysql_charset="utf8mb4",
)

daily_roy_predictions = Table(
    "daily_roy_predictions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("prediction_date", Date, nullable=False, index=True),
    Column("season_id", Integer, nullable=False),
    Column("player_id", String(32), nullable=False),
    Column("player", String(64), nullable=False),
    Column("team", String(8)),
    Column("roy_rank", Integer),       # = model1_rank (kept for the original /roy page)
    Column("model1_rank", Integer),    # Model 1 = roy_traditional (voter model)
    Column("model1_score", Double),    # 0-100 index
    Column("model1_share", Double),    # calibrated predicted vote share
    Column("model2_rank", Integer),    # Model 2 = roy_combined (traditional + impact)
    Column("model2_score", Double),
    Column("model2_share", Double),
    Column("mvp_index", Double),       # legacy (pre-trained-model ROY rows); not written any more
    Column("pts", Double),
    Column("mpg", Double),
    Column("games", Integer),
    Column("ts_pct", Double),
    Column("bpm", Double),
    Column("vorp", Double),
    Column("draft_pick", Integer),     # null = undrafted
    Column("team_win_pct", Double),
    Column("reb", Double),             # season per-game rebounds
    Column("ast", Double),             # season per-game assists
    Column("summary", Text),
    Column("rank_change", Integer),
    Column("recent_games", Text),      # JSON
    Column("created_at", DateTime, server_default=text("CURRENT_TIMESTAMP")),
    UniqueConstraint("prediction_date", "season_id", "player_id", name="uq_roy_date_season_player"),
    mysql_charset="utf8mb4",
)

daily_dpoy_predictions = Table(
    "daily_dpoy_predictions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("prediction_date", Date, nullable=False, index=True),
    Column("season_id", Integer, nullable=False),
    Column("player_id", String(32), nullable=False),
    Column("player", String(64), nullable=False),
    Column("team", String(8)),
    Column("pos", String(4)),
    Column("model1_rank", Integer),    # Model 1 = dpoy_traditional (voter model)
    Column("model1_score", Double),
    Column("model1_share", Double),
    Column("model2_rank", Integer),    # Model 2 = dpoy_impact (advanced impact)
    Column("model2_score", Double),
    Column("model2_share", Double),
    Column("blk_per_g", Double),
    Column("stl_per_g", Double),
    Column("trb_per_g", Double),
    Column("ast_per_g", Double),
    Column("dws", Double),
    Column("dbpm", Double),
    Column("blk_pct", Double),
    Column("stl_pct", Double),
    Column("drb_pct", Double),
    Column("team_drtg_rank", Integer),
    Column("prev_dpoy_share", Double),
    Column("games", Integer),
    Column("mpg", Double),
    Column("summary", Text),
    Column("rank_change", Integer),
    Column("recent_games", Text),      # JSON
    Column("created_at", DateTime, server_default=text("CURRENT_TIMESTAMP")),
    UniqueConstraint("prediction_date", "season_id", "player_id", name="uq_dpoy_date_season_player"),
    mysql_charset="utf8mb4",
)

nba_mvp_ladder = Table(
    "nba_mvp_ladder", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ladder_date", Date, nullable=False, index=True),   # the article's publish date
    Column("season_id", Integer, nullable=False),
    Column("ladder_rank", Integer, nullable=False),
    Column("player", String(64), nullable=False),
    Column("team", String(64)),                               # full team name, as NBA.com writes it
    Column("player_id", String(32)),                          # NBA.com id matched to daily_predictions (nullable)
    Column("author", String(128)),
    Column("title", String(255)),
    Column("url", String(512)),
    Column("fetched_at", DateTime, server_default=text("CURRENT_TIMESTAMP")),
    UniqueConstraint("ladder_date", "ladder_rank", name="uq_ladder_date_rank"),
    mysql_charset="utf8mb4",
)


# --------------------------------------------------------------------------- connection
def get_engine() -> Engine:
    load_dotenv(ROOT / ".env")
    raw = os.getenv("DATABASE_URL")
    if not raw:
        raise SystemExit("DATABASE_URL is not set - add it to .env")

    url = make_url(raw)
    if url.drivername in ("mysql", "tidb"):           # console strings often say mysql://
        url = url.set(drivername="mysql+pymysql")

    connect_args = {}
    if url.drivername.startswith("mysql"):
        connect_args["ssl"] = {"ca": certifi.where()}
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True, pool_recycle=300)


# --------------------------------------------------------------------------- schema migration
# create_all() only creates missing tables; columns added to daily_predictions after it was first
# created are added here (nullable, so existing rows are untouched).
ADDED_DAILY_COLUMNS = {"pts": "DOUBLE", "mpg": "DOUBLE", "ts_pct": "DOUBLE", "bpm": "DOUBLE", "vorp": "DOUBLE",
                       "is_rookie": "BOOLEAN", "reb": "DOUBLE", "ast": "DOUBLE"}
# Columns added to daily_roy_predictions when the trained two-model ROY output replaced the boilerplate
ADDED_ROY_COLUMNS = {"model1_rank": "INTEGER", "model2_rank": "INTEGER", "model2_score": "DOUBLE",
                     "games": "INTEGER", "draft_pick": "INTEGER", "team_win_pct": "DOUBLE",
                     "reb": "DOUBLE", "ast": "DOUBLE"}
ADDED_DPOY_COLUMNS = {"ast_per_g": "DOUBLE"}


def ensure_columns(engine: Engine, table: Table, added_columns: dict[str, str]) -> list[str]:
    """Create `table` if missing, then add any of `added_columns` it lacks (nullable; rows untouched)."""
    metadata.create_all(engine, tables=[table])  # no-op if the table exists
    existing = {c["name"] for c in inspect(engine).get_columns(table.name)}
    added = [name for name in added_columns if name not in existing]
    with engine.begin() as conn:
        for name in added:
            conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {name} {added_columns[name]} NULL"))
    return added


def ensure_daily_columns(engine: Engine) -> list[str]:
    return ensure_columns(engine, daily_predictions, ADDED_DAILY_COLUMNS)


INSIGHT_COLUMNS = {"summary": "TEXT", "rank_change": "INTEGER", "recent_games": "TEXT"}
AWARD_TABLES = {"mvp": daily_predictions, "roy": daily_roy_predictions, "dpoy": daily_dpoy_predictions}


def _int(v) -> int | None:
    return None if v is None or pd.isna(v) else int(v)


def _float(v) -> float | None:
    return None if v is None or pd.isna(v) else float(v)


# --------------------------------------------------------------------------- writers
def sync_historical(engine: Engine, csv_path: Path = HISTORICAL_CSV) -> int:
    """Replace the contents of historical_mvp with the CSV, in one transaction."""
    df = pd.read_csv(csv_path)
    missing = {"SEASON_ID", "PLAYER", "MVP_INDEX", "MVP_SHARE", "ELIGIBLE"} - set(df.columns)
    if missing:
        raise SystemExit(f"{csv_path.name} is missing columns: {sorted(missing)}")

    rows = [
        {"season_id": int(r.SEASON_ID), "player": str(r.PLAYER), "mvp_index": float(r.MVP_INDEX),
         "mvp_share": float(r.MVP_SHARE), "eligible": bool(r.ELIGIBLE)}
        for r in df.itertuples(index=False)
    ]
    with engine.begin() as conn:  # rolls back on any error, so the table is never half-written
        conn.execute(delete(historical_mvp))
        for i in range(0, len(rows), CHUNK):
            conn.execute(insert(historical_mvp), rows[i:i + CHUNK])
    return len(rows)


def write_daily_predictions(engine: Engine, pool: pd.DataFrame, season_id: int,
                            prediction_date: date | None = None) -> int:
    """Store one day's snapshot from compare_models.py (its scored `pool` DataFrame).
    Re-running on the same day replaces that day's rows."""
    prediction_date = prediction_date or date.today()
    added = ensure_daily_columns(engine)
    if added:
        print(f"daily_predictions: added columns {added}")
    rows = [
        {"prediction_date": prediction_date, "season_id": int(season_id),
         "player_id": str(r.PLAYER_ID), "player": str(r.PLAYER), "team": str(r.TEAM),
         "model1_rank": int(r.M1_RANK), "model1_score": float(r.M1_INDEX), "model1_share": float(r.M1_SHARE),
         "model2_rank": int(r.M2_RANK), "model2_share": float(r.M2_SHARE),
         "mvp_index": _float(r.MVP_INDEX),
         "pts": _float(r.PTS), "mpg": _float(r.MPG), "ts_pct": _float(r.TS_PCT),
         "bpm": _float(r.BPM), "vorp": _float(r.VORP), "reb": _float(r.REB), "ast": _float(r.AST),
         "is_rookie": bool(r.IS_ROOKIE) if hasattr(r, "IS_ROOKIE") else None}
        for r in pool.itertuples(index=False)
    ]
    with engine.begin() as conn:
        conn.execute(delete(daily_predictions).where(
            (daily_predictions.c.prediction_date == prediction_date)
            & (daily_predictions.c.season_id == int(season_id))))
        for i in range(0, len(rows), CHUNK):
            conn.execute(insert(daily_predictions), rows[i:i + CHUNK])
    return len(rows)


def _replace_day(engine: Engine, table: Table, rows: list[dict], season_id: int, prediction_date: date) -> int:
    """Replace one day's rows for a season in one transaction (re-runs never duplicate)."""
    with engine.begin() as conn:
        conn.execute(delete(table).where((table.c.prediction_date == prediction_date)
                                         & (table.c.season_id == int(season_id))))
        for i in range(0, len(rows), CHUNK):
            conn.execute(insert(table), rows[i:i + CHUNK])
    return len(rows)


def _model_cols(r) -> dict:
    return {"model1_rank": _int(r.m1_rank), "model1_score": _float(r.m1_score), "model1_share": _float(r.m1_share),
            "model2_rank": _int(r.m2_rank), "model2_score": _float(r.m2_score), "model2_share": _float(r.m2_share)}


def write_daily_roy(engine: Engine, roy: pd.DataFrame, season_id: int,
                    prediction_date: date | None = None) -> int:
    """Store one day's Rookie of the Year race (award_inference.predict_award("roy", ...))."""
    prediction_date = prediction_date or date.today()
    added = ensure_columns(engine, daily_roy_predictions, ADDED_ROY_COLUMNS)
    if added:
        print(f"daily_roy_predictions: added columns {added}")
    rows = [
        {"prediction_date": prediction_date, "season_id": int(season_id),
         "player_id": str(r.bbref_id), "player": str(r.player), "team": str(r.team),
         "roy_rank": _int(r.m1_rank), **_model_cols(r),
         "pts": _float(r.pts_per_g), "mpg": _float(r.mp_per_g), "games": _int(r.games),
         "ts_pct": _float(r.ts_pct), "bpm": _float(r.bpm), "vorp": _float(r.vorp),
         "draft_pick": _int(r.draft_pick), "team_win_pct": _float(r.team_win_pct),
         "reb": _float(r.trb_per_g), "ast": _float(r.ast_per_g)}
        for r in roy.itertuples(index=False)
    ]
    return _replace_day(engine, daily_roy_predictions, rows, season_id, prediction_date)


def write_daily_dpoy(engine: Engine, dpoy: pd.DataFrame, season_id: int,
                     prediction_date: date | None = None) -> int:
    """Store one day's Defensive Player of the Year race (award_inference.predict_award("dpoy", ...))."""
    prediction_date = prediction_date or date.today()
    added = ensure_columns(engine, daily_dpoy_predictions, ADDED_DPOY_COLUMNS)
    if added:
        print(f"daily_dpoy_predictions: added columns {added}")
    rows = [
        {"prediction_date": prediction_date, "season_id": int(season_id),
         "player_id": str(r.bbref_id), "player": str(r.player), "team": str(r.team), "pos": str(r.pos),
         **_model_cols(r),
         "blk_per_g": _float(r.blk_per_g), "stl_per_g": _float(r.stl_per_g), "trb_per_g": _float(r.trb_per_g),
         "ast_per_g": _float(r.ast_per_g),
         "dws": _float(r.dws), "dbpm": _float(r.dbpm), "blk_pct": _float(r.blk_pct),
         "stl_pct": _float(r.stl_pct), "drb_pct": _float(r.drb_pct),
         "team_drtg_rank": _int(r.team_drtg_rank), "prev_dpoy_share": _float(r.prev_dpoy_share),
         "games": _int(r.games), "mpg": _float(r.mp_per_g)}
        for r in dpoy.itertuples(index=False)
    ]
    return _replace_day(engine, daily_dpoy_predictions, rows, season_id, prediction_date)


def previous_ranks(engine: Engine, award: str, rank_col: str, season_id: int,
                   before: date) -> tuple[bool, dict[str, int]]:
    """(had_prior_day, {player_id: rank}) from the latest saved day before `before`."""
    table = AWARD_TABLES[award]
    with engine.connect() as conn:
        prior = conn.execute(select(func.max(table.c.prediction_date)).where(
            (table.c.prediction_date < before) & (table.c.season_id == int(season_id)))).scalar()
        if prior is None:
            return False, {}
        rows = conn.execute(select(table.c.player_id, table.c[rank_col]).where(
            (table.c.prediction_date == prior) & (table.c.season_id == int(season_id)))).all()
    return True, {str(pid): int(r) for pid, r in rows if r is not None}


def write_insights(engine: Engine, award: str, insights: list[dict], season_id: int,
                   prediction_date: date | None = None) -> int:
    """Attach summary / rank_change / recent_games to that day's rows (one UPDATE per player shown)."""
    prediction_date = prediction_date or date.today()
    table = AWARD_TABLES[award]
    added = ensure_columns(engine, table, INSIGHT_COLUMNS)
    if added:
        print(f"{table.name}: added columns {added}")
    with engine.begin() as conn:
        for ins in insights:
            conn.execute(table.update().where(
                (table.c.prediction_date == prediction_date) & (table.c.season_id == int(season_id))
                & (table.c.player_id == str(ins["player_id"]))
            ).values(summary=ins["summary"], rank_change=ins["rank_change"],
                     recent_games=json.dumps(ins["recent_games"])))
    return len(insights)


def write_mvp_ladder(engine: Engine, ladder: dict, season_id: int, player_ids: dict[int, str | None]) -> int:
    """Store one NBA.com ladder edition (replaces that edition's rows if re-run)."""
    metadata.create_all(engine, tables=[nba_mvp_ladder])
    ladder_date = date.fromisoformat(ladder["date"][:10])
    rows = [{"ladder_date": ladder_date, "season_id": int(season_id), "ladder_rank": e["rank"],
             "player": e["player"], "team": e["team"], "player_id": player_ids.get(e["rank"]),
             "author": ladder.get("author"), "title": ladder["title"][:255], "url": ladder["url"]}
            for e in ladder["entries"]]
    with engine.begin() as conn:
        conn.execute(delete(nba_mvp_ladder).where(nba_mvp_ladder.c.ladder_date == ladder_date))
        conn.execute(insert(nba_mvp_ladder), rows)
    return len(rows)


def row_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {t.name: conn.execute(select(func.count()).select_from(t)).scalar_one()
                for t in (historical_mvp, daily_predictions, daily_roy_predictions, daily_dpoy_predictions,
                          nba_mvp_ladder)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="only connect and print row counts")
    a = ap.parse_args()

    engine = get_engine()
    print(f"Connecting to {engine.url.render_as_string(hide_password=True)} ...")
    metadata.create_all(engine)  # CREATE TABLE IF NOT EXISTS for both tables
    if not a.check:
        n = sync_historical(engine)
        print(f"historical_mvp: replaced with {n} rows from {HISTORICAL_CSV.name}")
    for name, n in row_counts(engine).items():
        print(f"  {name}: {n} rows")


if __name__ == "__main__":
    main()
