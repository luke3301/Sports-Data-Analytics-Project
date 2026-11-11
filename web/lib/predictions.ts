import { cacheLife } from "next/cache";
import { db, seasonLabel } from "@/lib/db";

export type Prediction = {
  playerId: string;
  player: string;
  team: string | null;
  model1Rank: number | null;
  model1Score: number | null; // Model 1 MVP Index Score (0-100)
  model1Share: number | null; // Model 1 predicted award share (0-1)
  model2Rank: number | null;
  model2Share: number | null; // Model 2 ensemble predicted award share (0-1)
  mvpIndex: number | null; // unbounded MVP Dominance Index
};

export type PredictionDay = {
  date: string; // YYYY-MM-DD
  seasonId: number;
  season: string; // "2026-27"
  count: number;
  players: Prediction[];
};

type Row = {
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
};

const num = (v: unknown) => (v === null || v === undefined ? null : Number(v));

/** One day's MVP race from daily_predictions, ordered by Model 1 rank. Latest day if `date` is omitted.
 *  Uncached - callers decide caching. Returns null when there is no data for that day. */
export async function queryPredictions({ date, limit }: { date?: string; limit?: number } = {}): Promise<PredictionDay | null> {
  const conn = db();
  const target =
    date ??
    ((await conn.execute("SELECT MAX(prediction_date) AS d FROM daily_predictions")) as { d: string | null }[])[0]?.d;
  if (!target) return null;

  const rows = (await conn.execute(
    `SELECT prediction_date, season_id, player_id, player, team,
            model1_rank, model1_score, model1_share, model2_rank, model2_share, mvp_index
       FROM daily_predictions
      WHERE prediction_date = ?
      ORDER BY model1_rank IS NULL, model1_rank
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
      player: r.player,
      team: r.team,
      model1Rank: num(r.model1_rank),
      model1Score: num(r.model1_score),
      model1Share: num(r.model1_share),
      model2Rank: num(r.model2_rank),
      model2Share: num(r.model2_share),
      mvpIndex: num(r.mvp_index),
    })),
  };
}

/** Latest day's top N for the dashboard. Cached: the data changes once a night, so the page is
 *  served from cache and refreshed in the background at most every 10 minutes. */
export async function getLatestPredictions(limit: number): Promise<PredictionDay | null> {
  "use cache";
  cacheLife({ stale: 300, revalidate: 600, expire: 86400 });
  return queryPredictions({ limit });
}
