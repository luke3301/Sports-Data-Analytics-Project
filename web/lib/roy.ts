import { cacheLife } from "next/cache";
import { db, seasonLabel } from "@/lib/db";

export type RookiePrediction = {
  playerId: string;
  player: string;
  team: string | null;
  royRank: number | null;
  model1Score: number | null; // ranks the ROY race (see compare_models.py)
  model1Share: number | null;
  model2Share: number | null;
  mvpIndex: number | null; // Dominance Score
  pts: number | null;
  mpg: number | null;
  tsPct: number | null; // fraction (0.62 = 62%)
  bpm: number | null;
  vorp: number | null;
};

export type RoyDay = {
  date: string; // YYYY-MM-DD
  seasonId: number;
  season: string;
  count: number;
  players: RookiePrediction[];
};

type Row = {
  prediction_date: string;
  season_id: number;
  player_id: string;
  player: string;
  team: string | null;
  roy_rank: number | null;
  model1_score: number | null;
  model1_share: number | null;
  model2_share: number | null;
  mvp_index: number | null;
  pts: number | null;
  mpg: number | null;
  ts_pct: number | null;
  bpm: number | null;
  vorp: number | null;
};

const num = (v: unknown) => (v === null || v === undefined ? null : Number(v));

/** One day's Rookie of the Year race (rookies only), ordered by ROY rank. Latest day if `date` is
 *  omitted. Uncached - callers decide caching. Null when there is no data for that day. */
export async function queryRoy({ date, limit }: { date?: string; limit?: number } = {}): Promise<RoyDay | null> {
  const conn = db();
  const target =
    date ??
    ((await conn.execute("SELECT MAX(prediction_date) AS d FROM daily_roy_predictions")) as { d: string | null }[])[0]?.d;
  if (!target) return null;

  const rows = (await conn.execute(
    `SELECT prediction_date, season_id, player_id, player, team, roy_rank,
            model1_score, model1_share, model2_share, mvp_index, pts, mpg, ts_pct, bpm, vorp
       FROM daily_roy_predictions
      WHERE prediction_date = ?
      ORDER BY roy_rank IS NULL, roy_rank
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
      royRank: num(r.roy_rank),
      model1Score: num(r.model1_score),
      model1Share: num(r.model1_share),
      model2Share: num(r.model2_share),
      mvpIndex: num(r.mvp_index),
      pts: num(r.pts),
      mpg: num(r.mpg),
      tsPct: num(r.ts_pct),
      bpm: num(r.bpm),
      vorp: num(r.vorp),
    })),
  };
}

/** Latest day's top N rookies for the ROY page; cached like the MVP page (refreshes at most every 10 min). */
export async function getLatestRoy(limit: number): Promise<RoyDay | null> {
  "use cache";
  cacheLife({ stale: 300, revalidate: 600, expire: 86400 });
  return queryRoy({ limit });
}
