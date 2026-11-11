"""
Sync MVP data to TiDB Serverless (MySQL-compatible).

Tables (created if missing):
  historical_mvp     one row per player-season from data/processed/historical_mvp_index.csv
  daily_predictions  live MVP race snapshots from compare_models.py, one row per player per day

Usage:
    python db_sync.py              # create tables, replace historical_mvp with the CSV
    python db_sync.py --check      # connect and print row counts only

Connection: DATABASE_URL in .env, e.g.
    DATABASE_URL=mysql+pymysql://<user>:<password>@<host>:4000/<database>
TiDB Serverless requires TLS; if the URL has no ssl_* options, the certifi CA bundle is used.
"""
from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

import certifi
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import (Boolean, Column, Date, DateTime, Double, Integer, MetaData, String, Table,
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
    Column("created_at", DateTime, server_default=text("CURRENT_TIMESTAMP")),
    UniqueConstraint("prediction_date", "season_id", "player_id", name="uq_daily_date_season_player"),
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
ADDED_DAILY_COLUMNS = {"pts": "DOUBLE", "mpg": "DOUBLE", "ts_pct": "DOUBLE", "bpm": "DOUBLE", "vorp": "DOUBLE"}


def ensure_daily_columns(engine: Engine) -> list[str]:
    metadata.create_all(engine, tables=[daily_predictions])  # no-op if the table exists
    existing = {c["name"] for c in inspect(engine).get_columns("daily_predictions")}
    added = [name for name in ADDED_DAILY_COLUMNS if name not in existing]
    with engine.begin() as conn:
        for name in added:
            conn.execute(text(f"ALTER TABLE daily_predictions ADD COLUMN {name} {ADDED_DAILY_COLUMNS[name]} NULL"))
    return added


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
         "bpm": _float(r.BPM), "vorp": _float(r.VORP)}
        for r in pool.itertuples(index=False)
    ]
    with engine.begin() as conn:
        conn.execute(delete(daily_predictions).where(
            (daily_predictions.c.prediction_date == prediction_date)
            & (daily_predictions.c.season_id == int(season_id))))
        for i in range(0, len(rows), CHUNK):
            conn.execute(insert(daily_predictions), rows[i:i + CHUNK])
    return len(rows)


def row_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {t.name: conn.execute(select(func.count()).select_from(t)).scalar_one()
                for t in (historical_mvp, daily_predictions)}


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
