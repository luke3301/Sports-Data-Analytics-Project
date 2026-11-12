import { cacheLife } from "next/cache";
import { db, seasonLabel } from "@/lib/db";
import { INSIGHT_COLUMNS, parseInsight, type Insight, type InsightRow } from "@/lib/insights";

export type Prediction = {
  insight: Insight; // summary, rank change, last 3 games (top of the race only)
  playerId: string;
  player: string;
  team: string | null;
  model1Rank: number | null;
  model1Score: number | null; // Model 1 MVP Index Score (0-100)
  model1Share: number | null; // Model 1 predicted award share (0-1)
  model2Rank: number | null;
  model2Share: number | null; // Model 2 ensemble predicted award share (0-1)
  mvpIndex: number | null; // unbounded MVP Dominance Index ("Dominance Score" in the UI)
  // Season-to-date box score context (null for days saved before these columns existed)
  pts: number | null;
  reb: number | null; // season per-game rebounds
  ast: number | null; // season per-game assists
  mpg: number | null;
  tsPct: number | null; // true shooting as a fraction (0.62 = 62%)
  bpm: number | null;
  vorp: number | null;
};

/** Which model's ranking orders the list. Model 2 is the featured model. */
export type SortModel = "model1" | "model2";

export type PredictionDay = {
  date: string; // YYYY-MM-DD
  seasonId: number;
  season: string; // "2026-27"
  count: number;
  players: Prediction[];
};

type Row = InsightRow & {
  prediction_date: string;
  season_id: number;
  player_id: string;
  player: string;
  team: string | null;
  model1_rank: number | null;
  model1_score: number | null;
  model1_share: number | null;
  model2_rank: number | null;
  model2_share: number | null;
  mvp_index: number | null;
  pts: number | null;
  reb: number | null;
  ast: number | null;
  mpg: number | null;
  ts_pct: number | null;
  bpm: number | null;
  vorp: number | null;
};

const ORDER_BY: Record<SortModel, string> = {
  model2: "model2_rank IS NULL, model2_rank",
  model1: "model1_rank IS NULL, model1_rank",
};

const num = (v: unknown) => (v === null || v === undefined ? null : Number(v));

/** One day's MVP race from daily_predictions, ordered by Model 2 rank unless `sort` says otherwise.
 *  Latest day if `date` is omitted. Uncached - callers decide caching. Null when there is no data. */
export async function queryPredictions({
  date,
  limit,
  sort = "model2",
}: { date?: string; limit?: number; sort?: SortModel } = {}): Promise<PredictionDay | null> {
  const conn = db();
  const target =
    date ??
    ((await conn.execute("SELECT MAX(prediction_date) AS d FROM daily_predictions")) as { d: string | null }[])[0]?.d;
  if (!target) return null;

  const rows = (await conn.execute(
    `SELECT prediction_date, season_id, player_id, player, team,
            model1_rank, model1_score, model1_share, model2_rank, model2_share, mvp_index,
            pts, reb, ast, mpg, ts_pct, bpm, vorp, ${INSIGHT_COLUMNS}
       FROM daily_predictions
      WHERE prediction_date = ?
      ORDER BY ${ORDER_BY[sort]}
      ${limit ? "LIMIT ?" : ""}`,
    limit ? [target, limit] : [target],
  )) as Row[];
  if (rows.length === 0) return null;

  const seasonId = Number(rows[0].season_id);
  return {
    date: String(target).slice(0, 10),
    seasonId,
    season: seasonLabel(seasonId),
    count: rows.length,
    players: rows.map((r) => ({
      playerId: String(r.player_id),
      insight: parseInsight(r),
      player: r.player,
      team: r.team,
      model1Rank: num(r.model1_rank),
      model1Score: num(r.model1_score),
      model1Share: num(r.model1_share),
      model2Rank: num(r.model2_rank),
      model2Share: num(r.model2_share),
      mvpIndex: num(r.mvp_index),
      pts: num(r.pts),
      reb: num(r.reb),
      ast: num(r.ast),
      mpg: num(r.mpg),
      tsPct: num(r.ts_pct),
      bpm: num(r.bpm),
      vorp: num(r.vorp),
    })),
  };
}

/** Latest day's top N by Model 2 rank for the dashboard. Cached: the data changes once a night, so the page is
 *  served from cache and refreshed in the background at most every 10 minutes. */
export async function getLatestPredictions(limit: number): Promise<PredictionDay | null> {
  "use cache";
  cacheLife({ stale: 300, revalidate: 600, expire: 86400 });
  return queryPredictions({ limit });
}
