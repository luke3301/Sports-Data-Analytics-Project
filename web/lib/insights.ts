// Player insights written nightly by insights.py: a 1-2 sentence summary, the rank change vs the
// previous day (+ = climbed) and the last 3 games' box scores (stored as JSON text).

export type RecentGame = {
  date: string; // YYYY-MM-DD
  opp: string | null;
  home: boolean;
  result: string | null; // "W, 124-109"
  pts: number | null;
  reb: number | null;
  ast: number | null;
  stl: number | null;
  blk: number | null;
  fg_pct: number | null; // fraction
};

export type Insight = {
  summary: string | null;
  rankChange: number | null;
  recentGames: RecentGame[];
};

export type InsightRow = { summary: string | null; rank_change: number | null; recent_games: string | null };

/** Columns every award query selects for insights. */
export const INSIGHT_COLUMNS = "summary, rank_change, recent_games";

export function parseInsight(r: InsightRow): Insight {
  let recentGames: RecentGame[] = [];
  if (r.recent_games) {
    try {
      const parsed = JSON.parse(r.recent_games);
      if (Array.isArray(parsed)) recentGames = parsed;
    } catch {
      recentGames = []; // malformed JSON never breaks the page
    }
  }
  return {
    summary: r.summary ?? null,
    rankChange: r.rank_change === null || r.rank_change === undefined ? null : Number(r.rank_change),
    recentGames,
  };
}
