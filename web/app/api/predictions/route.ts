import type { NextRequest } from "next/server";
import { db, seasonLabel } from "@/lib/db";

// Runs at request time: reading request.nextUrl is runtime data under Cache Components, so this
// handler is never prerendered. The CDN Cache-Control header below absorbs repeat traffic.

type PredictionRow = {
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

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const num = (v: unknown) => (v === null || v === undefined ? null : Number(v));

/**
 * GET /api/predictions            -> latest day's MVP race (every eligible player)
 * GET /api/predictions?date=YYYY-MM-DD
 * GET /api/predictions?limit=10   -> top N by Model 1 rank
 */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const date = params.get("date");
  const limitParam = params.get("limit");

  if (date && !DATE_RE.test(date)) {
    return Response.json({ error: "date must be YYYY-MM-DD" }, { status: 400 });
  }
  const limit = limitParam === null ? null : Number(limitParam);
  if (limit !== null && (!Number.isInteger(limit) || limit < 1 || limit > 500)) {
    return Response.json({ error: "limit must be an integer from 1 to 500" }, { status: 400 });
  }

  try {
    const conn = db();
    const target = date
      ? date
      : ((await conn.execute("SELECT MAX(prediction_date) AS d FROM daily_predictions")) as { d: string | null }[])[0]?.d;

    if (!target) {
      return Response.json({ error: "no predictions found" }, { status: 404 });
    }

    const rows = (await conn.execute(
      `SELECT prediction_date, season_id, player_id, player, team,
              model1_rank, model1_score, model1_share, model2_rank, model2_share, mvp_index
         FROM daily_predictions
        WHERE prediction_date = ?
        ORDER BY model1_rank IS NULL, model1_rank
        ${limit ? "LIMIT ?" : ""}`,
      limit ? [target, limit] : [target],
    )) as PredictionRow[];

    if (rows.length === 0) {
      return Response.json({ error: `no predictions for ${target}` }, { status: 404 });
    }

    const players = rows.map((r) => ({
      playerId: String(r.player_id),
      player: r.player,
      team: r.team,
      model1Rank: num(r.model1_rank),
      model1Score: num(r.model1_score),
      model1Share: num(r.model1_share),
      model2Rank: num(r.model2_rank),
      model2Share: num(r.model2_share),
      mvpIndex: num(r.mvp_index),
    }));
    const seasonId = Number(rows[0].season_id);

    return Response.json(
      {
        date: String(target).slice(0, 10),
        seasonId,
        season: seasonLabel(seasonId),
        count: players.length,
        players,
      },
      // Data changes once a night: let Vercel's CDN serve it for 5 min, then refresh in the background
      { headers: { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=3600" } },
    );
  } catch (err) {
    console.error("GET /api/predictions failed:", err);
    return Response.json({ error: "database query failed" }, { status: 500 });
  }
}
