import { db } from "@/lib/db";

// A player's daily trajectory in one award race over the current season: the featured model's rank and
// predicted vote share on every saved day (MVP = Model 2, ROY and DPOY = Model 1, as on the pages).

export const AWARDS = {
  mvp: { table: "daily_predictions", rank: "model2_rank", share: "model2_share" },
  roy: { table: "daily_roy_predictions", rank: "model1_rank", share: "model1_share" },
  dpoy: { table: "daily_dpoy_predictions", rank: "model1_rank", share: "model1_share" },
} as const;

export type Award = keyof typeof AWARDS;

export const isAward = (v: string | null): v is Award => v !== null && v in AWARDS;

export type TrendPoint = { date: string; rank: number | null; voteShare: number | null };

export type Trend = { award: Award; playerId: string; player: string | null; seasonId: number | null; points: TrendPoint[] };

type Row = { prediction_date: string; season_id: number; player: string; rank_value: number | null; share_value: number | null };

/** Trend over the latest season for one player. Table/column names come only from the AWARDS whitelist. */
export async function queryTrend(award: Award, playerId: string): Promise<Trend> {
  const { table, rank, share } = AWARDS[award];
  const rows = (await db().execute(
    `SELECT prediction_date, season_id, player, ${rank} AS rank_value, ${share} AS share_value
       FROM ${table}
      WHERE player_id = ?
        AND season_id = (SELECT MAX(season_id) FROM ${table})
      ORDER BY prediction_date`,
    [playerId],
  )) as Row[];
  return {
    award,
    playerId,
    player: rows.at(-1)?.player ?? null,
    seasonId: rows.length ? Number(rows[0].season_id) : null,
    points: rows.map((r) => ({
      date: String(r.prediction_date).slice(0, 10),
      rank: r.rank_value === null ? null : Number(r.rank_value),
      voteShare: r.share_value === null ? null : Number(r.share_value),
    })),
  };
}
