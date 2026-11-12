import type { NextRequest } from "next/server";
import { isAward, queryTrend } from "@/lib/trends";

// Request-time handler (reads request.nextUrl). Data changes once a night, so the CDN caches it.

const PLAYER_ID_RE = /^[A-Za-z0-9]{1,32}$/; // NBA.com ids (digits) and bbref ids (letters + digits)

/**
 * GET /api/trends?award=mvp|roy|dpoy&playerId=...
 * -> { award, playerId, player, seasonId, points: [{ date, rank, voteShare }] } over the current season
 */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const award = params.get("award");
  const playerId = params.get("playerId");

  if (!isAward(award)) {
    return Response.json({ error: "award must be mvp, roy or dpoy" }, { status: 400 });
  }
  if (!playerId || !PLAYER_ID_RE.test(playerId)) {
    return Response.json({ error: "playerId is required (letters and digits only)" }, { status: 400 });
  }

  try {
    const trend = await queryTrend(award, playerId);
    if (trend.points.length === 0) {
      return Response.json({ error: `no ${award} history for ${playerId}` }, { status: 404 });
    }
    return Response.json(trend, {
      headers: { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=3600" },
    });
  } catch (err) {
    console.error("GET /api/trends failed:", err);
    return Response.json({ error: "database query failed" }, { status: 500 });
  }
}
