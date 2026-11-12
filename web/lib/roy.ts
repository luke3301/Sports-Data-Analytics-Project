import { cacheLife } from "next/cache";
import { db, seasonLabel } from "@/lib/db";
import { INSIGHT_COLUMNS, parseInsight, type Insight, type InsightRow } from "@/lib/insights";

// Rookie of the Year race (daily_roy_predictions, written by award_inference.py via db_sync.py).
//   Model 1 = Traditional Voter (roy_traditional): scoring, minutes, games, draft slot
//   Model 2 = Combined Impact   (roy_combined):    traditional + BPM and team win %

export type RookiePrediction = {
  insight: Insight; // summary, rank change, last 3 games (top of the race only)
  playerId: string; // Basketball-Reference player id
  player: string;
  team: string | null; // Basketball-Reference code (BRK, CHO, PHO): display via lib/teams
  model1Rank: number | null;
  model1Score: number | null; // 0-100
  model1Share: number | null; // predicted ROY vote share (0-1)
  model2Rank: number | null;
  model2Score: number | null;
  model2Share: number | null;
  pts: number | null;
  reb: number | null; // season per-game rebounds
  ast: number | null; // season per-game assists
  mpg: number | null;
  games: number | null;
  tsPct: number | null; // fraction (0.62 = 62%)
  bpm: number | null;
  vorp: number | null;
  draftPick: number | null; // null = undrafted
  teamWinPct: number | null;
};

export type RoyDay = { date: string; seasonId: number; season: string; count: number; players: RookiePrediction[] };

type Row = InsightRow & {
  prediction_date: string; season_id: number; player_id: string; player: string; team: string | null;
  model1_rank: number | null; model1_score: number | null; model1_share: number | null;
  model2_rank: number | null; model2_score: number | null; model2_share: number | null;
  pts: number | null; reb: number | null; ast: number | null; mpg: number | null; games: number | null; ts_pct: number | null;
  bpm: number | null; vorp: number | null; draft_pick: number | null; team_win_pct: number | null;
};

const num = (v: unknown) => (v === null || v === undefined ? null : Number(v));

/** One day's ROY race ordered by Model 1 (Traditional Voter). Latest day if `date` is omitted.
 *  Uncached - callers decide caching. Null when there is no data for that day. */
export async function queryRoy({ date, limit }: { date?: string; limit?: number } = {}): Promise<RoyDay | null> {
  const conn = db();
  const target =
    date ??
    ((await conn.execute("SELECT MAX(prediction_date) AS d FROM daily_roy_predictions")) as { d: string | null }[])[0]?.d;
  if (!target) return null;

  const rows = (await conn.execute(
    `SELECT prediction_date, season_id, player_id, player, team,
            model1_rank, model1_score, model1_share, model2_rank, model2_score, model2_share,
            pts, reb, ast, mpg, games, ts_pct, bpm, vorp, draft_pick, team_win_pct, ${INSIGHT_COLUMNS}
       FROM daily_roy_predictions
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
      insight: parseInsight(r),
      player: r.player,
      team: r.team,
      model1Rank: num(r.model1_rank),
      model1Score: num(r.model1_score),
      model1Share: num(r.model1_share),
      model2Rank: num(r.model2_rank),
      model2Score: num(r.model2_score),
      model2Share: num(r.model2_share),
      pts: num(r.pts),
      reb: num(r.reb),
      ast: num(r.ast),
      mpg: num(r.mpg),
      games: num(r.games),
      tsPct: num(r.ts_pct),
      bpm: num(r.bpm),
      vorp: num(r.vorp),
      draftPick: num(r.draft_pick),
      teamWinPct: num(r.team_win_pct),
    })),
  };
}

/** Latest day's top N for the ROY page; cached like the MVP page (refreshes at most every 10 min). */
export async function getLatestRoy(limit: number): Promise<RoyDay | null> {
  "use cache";
  cacheLife({ stale: 300, revalidate: 600, expire: 86400 });
  return queryRoy({ limit });
}
