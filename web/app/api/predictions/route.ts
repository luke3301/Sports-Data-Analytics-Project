import type { NextRequest } from "next/server";
import { queryPredictions } from "@/lib/predictions";

// Runs at request time: reading request.nextUrl is runtime data under Cache Components, so this
// handler is never prerendered. The CDN Cache-Control header below absorbs repeat traffic.

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

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
  const limit = limitParam === null ? undefined : Number(limitParam);
  if (limit !== undefined && (!Number.isInteger(limit) || limit < 1 || limit > 500)) {
    return Response.json({ error: "limit must be an integer from 1 to 500" }, { status: 400 });
  }

  try {
    const day = await queryPredictions({ date: date ?? undefined, limit });
    if (!day) {
      return Response.json({ error: date ? `no predictions for ${date}` : "no predictions found" }, { status: 404 });
    }
    // Data changes once a night: let Vercel's CDN serve it for 5 min, then refresh in the background
    return Response.json(day, {
      headers: { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=3600" },
    });
  } catch (err) {
    console.error("GET /api/predictions failed:", err);
    return Response.json({ error: "database query failed" }, { status: 500 });
  }
}
