import { queryLadder } from "@/lib/ladder";
import { connection } from "next/server";

/** GET /api/mvp-ladder -> the latest official NBA.com Kia MVP Ladder, with our Model 2 rank per player. */
export async function GET() {
  await connection(); // request-time handler (no request input, so opt out of prerendering explicitly)
  try {
    const ladder = await queryLadder();
    if (!ladder) {
      return Response.json({ error: "no MVP ladder found" }, { status: 404 });
    }
    return Response.json(ladder, {
      headers: { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=3600" },
    });
  } catch (err) {
    console.error("GET /api/mvp-ladder failed:", err);
    return Response.json({ error: "database query failed" }, { status: 500 });
  }
}
