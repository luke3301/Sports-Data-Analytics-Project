import { cacheLife } from "next/cache";
import { db, seasonLabel } from "@/lib/db";

// Defensive Player of the Year race (daily_dpoy_predictions, written by award_inference.py via db_sync.py).
//   Model 1 = Traditional Voter (dpoy_traditional): reputation, center, top-5 team defense, BLK/STL/REB
//   Model 2 = Advanced Impact   (dpoy_impact):      DBPM, DWS, BLK%, STL%, DRB%

export type DefenderPrediction = {
  playerId: string; // Basketball-Reference player id
  player: string;
  team: string | null; // Basketball-Reference code (BRK, CHO, PHO): display via lib/teams
  pos: string | null;
  model1Rank: number | null;
  model1Score: number | null; // 0-100
  model1Share: number | null; // predicted DPOY vote share (0-1)
  model2Rank: number | null;
  model2Score: number | null;
  model2Share: number | null;
  blk: number | null; // per game
  stl: number | null;
  reb: number | null;
  dws: number | null;
  dbpm: number | null;
  teamDrtgRank: number | null; // 1 = best team defense
  prevDpoyShare: number | null; // last season's DPOY vote share (reputation)
  games: number | null;
  mpg: number | null;
};

export type DpoyDay = { date: string; seasonId: number; season: string; count: number; players: DefenderPrediction[] };

type Row = {
  prediction_date: string; season_id: number; player_id: string; player: string; team: string | null; pos: string | null;
  model1_rank: number | null; model1_score: number | null; model1_share: number | null;
  model2_rank: number | null; model2_score: number | null; model2_share: number | null;
  blk_per_g: number | null; stl_per_g: number | null; trb_per_g: number | null; dws: number | null; dbpm: number | null;
  team_drtg_rank: number | null; prev_dpoy_share: number | null; games: number | null; mpg: number | null;
};

const num = (v: unknown) => (v === null || v === undefined ? null : Number(v));

/** One day's DPOY race ordered by Model 1 (Traditional Voter). Latest day if `date` is omitted.
 *  Uncached - callers decide caching. Null when there is no data for that day. */
export async function queryDpoy({ date, limit }: { date?: string; limit?: number } = {}): Promise<DpoyDay | null> {
  const conn = db();
  const target =
    date ??
    ((await conn.execute("SELECT MAX(prediction_date) AS d FROM daily_dpoy_predictions")) as { d: string | null }[])[0]?.d;
  if (!target) return null;

  const rows = (await conn.execute(
    `SELECT prediction_date, season_id, player_id, player, team, pos,
            model1_rank, model1_score, model1_share, model2_rank, model2_score, model2_share,
            blk_per_g, stl_per_g, trb_per_g, dws, dbpm, team_drtg_rank, prev_dpoy_share, games, mpg
       FROM daily_dpoy_predictions
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
      pos: r.pos,
      model1Rank: num(r.model1_rank),
      model1Score: num(r.model1_score),
      model1Share: num(r.model1_share),
      model2Rank: num(r.model2_rank),
      model2Score: num(r.model2_score),
      model2Share: num(r.model2_share),
      blk: num(r.blk_per_g),
      stl: num(r.stl_per_g),
      reb: num(r.trb_per_g),
      dws: num(r.dws),
      dbpm: num(r.dbpm),
      teamDrtgRank: num(r.team_drtg_rank),
      prevDpoyShare: num(r.prev_dpoy_share),
      games: num(r.games),
      mpg: num(r.mpg),
    })),
  };
}

/** Latest day's top N for the DPOY page; cached like the MVP page (refreshes at most every 10 min). */
export async function getLatestDpoy(limit: number): Promise<DpoyDay | null> {
  "use cache";
  cacheLife({ stale: 300, revalidate: 600, expire: 86400 });
  return queryDpoy({ limit });
}
