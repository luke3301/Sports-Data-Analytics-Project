import { connect } from "@tidbcloud/serverless";

type Connection = ReturnType<typeof connect>;

// Read-only TiDB connection (HTTP-based serverless driver, so no connection pool is needed
// in short-lived Vercel functions). Server-side only: never import this from a client component.
let conn: Connection | null = null;

export function db(): Connection {
  if (!conn) {
    const url = process.env.TIDB_READONLY_URL;
    if (!url) {
      throw new Error("TIDB_READONLY_URL is not set (web/.env.local locally, Project Settings on Vercel)");
    }
    conn = connect({ url });
  }
  return conn;
}

/** 2027 -> "2026-27" */
export function seasonLabel(seasonId: number): string {
  return `${seasonId - 1}-${String(seasonId).slice(-2)}`;
}
