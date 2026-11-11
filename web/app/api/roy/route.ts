import type { NextRequest } from "next/server";
import { queryRoy } from "@/lib/roy";

// Runs at request time (reads request.nextUrl). Every row in daily_roy_predictions is a rookie.
// Rows carry both models: Model 1 = Traditional Voter, Model 2 = Combined Impact.

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * GET /api/roy             -> latest day's Rookie of the Year race (rookies only)
 * GET /api/roy?date=YYYY-MM-DD
 * GET /api/roy?limit=10    -> top N by Model 1 (Traditional Voter) rank
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
    const day = await queryRoy({ date: date ?? undefined, limit });
    if (!day) {
      return Response.json({ error: date ? `no ROY predictions for ${date}` : "no ROY predictions found" }, { status: 404 });
    }
    return Response.json(day, {
      headers: { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=3600" },
    });
  } catch (err) {
    console.error("GET /api/roy failed:", err);
    return Response.json({ error: "database query failed" }, { status: 500 });
  }
}
