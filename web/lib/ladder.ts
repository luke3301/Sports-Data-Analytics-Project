import { cacheLife } from "next/cache";
import { db } from "@/lib/db";

// The official NBA.com Kia MVP Ladder (nba_mvp_ladder, scraped nightly by insights.py), joined to our
// MVP race so each entry shows where Model 2 ranks the same player today.

export type LadderEntry = {
  ladderRank: number;
  player: string;
  team: string | null; // full team name as NBA.com writes it
  playerId: string | null; // NBA.com id, when the player is in our MVP race
  ourRank: number | null; // our Model 2 rank on our latest day (null = not in our ranked pool)
};

export type Ladder = {
  date: string; // article publish date, YYYY-MM-DD
  author: string | null;
  title: string;
  url: string;
  entries: LadderEntry[];
};

type Row = {
  ladder_date: string; ladder_rank: number; player: string; team: string | null; player_id: string | null;
  author: string | null; title: string; url: string; our_rank: number | null;
};

export async function queryLadder(): Promise<Ladder | null> {
  const rows = (await db().execute(
    `SELECT l.ladder_date, l.ladder_rank, l.player, l.team, l.player_id, l.author, l.title, l.url,
            p.model2_rank AS our_rank
       FROM nba_mvp_ladder l
       LEFT JOIN daily_predictions p
         ON p.player_id = l.player_id
        AND p.prediction_date = (SELECT MAX(prediction_date) FROM daily_predictions)
      WHERE l.ladder_date = (SELECT MAX(ladder_date) FROM nba_mvp_ladder)
      ORDER BY l.ladder_rank`,
  )) as Row[];
  if (rows.length === 0) return null;
  return {
    date: String(rows[0].ladder_date).slice(0, 10),
    author: rows[0].author,
    title: rows[0].title,
    url: rows[0].url,
    entries: rows.map((r) => ({
      ladderRank: Number(r.ladder_rank),
      player: r.player,
      team: r.team,
      playerId: r.player_id === null ? null : String(r.player_id),
      ourRank: r.our_rank === null ? null : Number(r.our_rank),
    })),
  };
}

/** Cached like the race pages; the ladder itself changes about once a week. */
export async function getLatestLadder(): Promise<Ladder | null> {
  "use cache";
  cacheLife({ stale: 300, revalidate: 600, expire: 86400 });
  return queryLadder();
}
