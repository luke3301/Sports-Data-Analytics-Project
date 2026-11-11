// Number and date formatting shared by the award pages.

export const DASH = "—";

/** One decimal: 30.1 */
export const one = (v: number | null) => (v === null ? DASH : v.toFixed(1));
/** Signed, one decimal: +17.2 / -1.5 */
export const signed = (v: number | null) => (v === null ? DASH : `${v > 0 ? "+" : ""}${v.toFixed(1)}`);
/** Fraction as a percentage: 0.622 -> 62.2% */
export const pct = (v: number | null) => (v === null ? DASH : `${(v * 100).toFixed(1)}%`);
/** Rank: #2 */
export const rank = (v: number | null) => (v === null ? DASH : `#${v}`);
/** Whole number: 11 */
export const int = (v: number | null) => (v === null ? DASH : String(Math.round(v)));

/** "2026-11-11" -> "November 11, 2026" (UTC, so the date never shifts with the server's time zone) */
export function formatDate(isoDate: string) {
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString("en-US", {
    timeZone: "UTC", month: "long", day: "numeric", year: "numeric",
  });
}
