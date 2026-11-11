import type { ReactNode } from "react";
import { SiteNav, type NavHref } from "@/components/site-nav";
import { DASH, formatDate } from "@/lib/format";
import { teamCode, teamName } from "@/lib/teams";

// Shared layout for every award race page (MVP, ROY, DPOY): header + nav, a big #1 card, a table of
// the rest of the top 10 (stacked rows on phones), and a methodology footer. Pages only supply data
// and column definitions, so the three races always look the same.

// --------------------------------------------------------------------------- page shell
export function RacePage({
  title, current, day, emptyText, children, footer,
}: {
  title: string;
  current: NavHref;
  day: { season: string; date: string } | null;
  emptyText: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-16 px-6 py-12 sm:gap-20 sm:px-10 sm:py-20">
      <header className="flex flex-col gap-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-baseline sm:justify-between">
          <p className="text-sm font-bold uppercase tracking-[0.2em] text-amber-400">{title}</p>
          <SiteNav current={current} />
        </div>
        {day && (
          <p className="text-sm text-zinc-500">
            {day.season} season · Updated {formatDate(day.date)}
          </p>
        )}
      </header>

      {day ? children : <p className="text-lg text-zinc-400">{emptyText}</p>}

      <footer className="mt-auto flex flex-col gap-3 border-t border-zinc-900 pt-8 text-sm leading-relaxed text-zinc-500">
        {footer}
      </footer>
    </main>
  );
}

// --------------------------------------------------------------------------- #1 card
export type StatItem = { label: string; value: string; note?: string };

function Stat({ label, value, note }: StatItem) {
  return (
    <div className="flex flex-col gap-2">
      <dt className="text-xs font-medium uppercase tracking-[0.14em] text-zinc-500">{label}</dt>
      <dd className="text-3xl font-semibold tabular-nums text-zinc-50 sm:text-4xl">
        {value}
        {note && <span className="ml-1.5 text-base font-normal text-zinc-500">{note}</span>}
      </dd>
    </div>
  );
}

export function LeaderCard({
  badge, badgeShort, player, team, stats,
}: {
  badge: string; // e.g. "#1 · Projected MVP"
  badgeShort?: string; // shown on phones when the full badge would wrap
  player: string;
  team: string | null;
  stats: StatItem[];
}) {
  return (
    <section aria-labelledby="leader-name" className="rounded-3xl border border-zinc-800 bg-zinc-900/40 p-8 sm:p-12 lg:p-16">
      <p className="inline-flex items-center rounded-full bg-amber-400 px-4 py-1.5 text-xs font-bold uppercase tracking-[0.18em] text-zinc-950">
        {badgeShort ? (
          <>
            <span className="sm:hidden">{badgeShort}</span>
            <span className="hidden sm:inline">{badge}</span>
          </>
        ) : (
          badge
        )}
      </p>
      <h1 id="leader-name" className="mt-8 text-4xl font-bold tracking-tight [overflow-wrap:anywhere] text-zinc-50 min-[400px]:text-5xl sm:text-7xl lg:text-8xl">
        {player}
      </h1>
      <p className="mt-4 text-lg text-zinc-400 sm:text-xl">{teamName(team)}</p>

      <dl className="mt-12 grid grid-cols-2 gap-x-8 gap-y-10 border-t border-zinc-800 pt-10 sm:mt-16 sm:grid-cols-3">
        {stats.map((s) => (
          <Stat key={s.label} {...s} />
        ))}
      </dl>
    </section>
  );
}

// --------------------------------------------------------------------------- top-10 table
export type Column<T> = {
  header: string;
  cell: (row: T) => string;
  /** primary = the featured model's numbers (bright, large); stat = box score; muted = secondary */
  tone?: "primary" | "stat" | "muted";
  /** hide on tablets, show from laptop width (keeps the table from scrolling sideways) */
  wideOnly?: boolean;
  /** last column: the other model's rank, set off by a divider as a comparison */
  comparison?: boolean;
};

const TH = "whitespace-nowrap py-4 px-3 text-xs font-medium uppercase tracking-[0.12em] text-zinc-500";
const TONE = { primary: "text-lg text-zinc-100", stat: "text-zinc-300", muted: "text-zinc-400" };

export function RaceTable<T>({
  title, rows, rowKey, rank, player, team, columns, mobileDetails, mobilePrimary, mobileSecondary,
}: {
  title: string;
  rows: T[];
  rowKey: (r: T) => string;
  rank: (r: T) => number | null;
  player: (r: T) => string;
  team: (r: T) => string | null;
  columns: Column<T>[];
  /** phone rows: small pieces under the name (team is added first), each kept on one line */
  mobileDetails: (r: T) => string[];
  mobilePrimary: (r: T) => string;
  mobileSecondary: (r: T) => string;
}) {
  return (
    <section aria-labelledby="contenders" className="flex flex-col gap-6">
      <h2 id="contenders" className="text-sm font-medium uppercase tracking-[0.14em] text-zinc-500">
        {title}
      </h2>

      {/* Phones: stacked rows, so the key numbers are visible without sideways scrolling */}
      <ol className="flex flex-col sm:hidden">
        {rows.map((r) => {
          const details = [teamCode(team(r)) ?? DASH, ...mobileDetails(r)];
          return (
            <li key={rowKey(r)} className="flex items-center gap-4 border-b border-zinc-900 py-5 last:border-0">
              <span className="w-6 shrink-0 tabular-nums text-zinc-500">{rank(r) ?? DASH}</span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-lg font-medium text-zinc-100">{player(r)}</p>
                {/* each piece stays on one line; wrapping only happens between pieces */}
                <p className="mt-1 flex flex-wrap gap-x-1.5 text-sm tabular-nums text-zinc-500">
                  {details.map((d, i) => (
                    <span key={i} className="whitespace-nowrap">
                      {i < details.length - 1 ? `${d} ·` : d}
                    </span>
                  ))}
                </p>
              </div>
              <div className="shrink-0 text-right tabular-nums">
                <p className="text-lg text-zinc-100">{mobilePrimary(r)}</p>
                <p className="mt-1 text-sm text-zinc-500">{mobileSecondary(r)}</p>
              </div>
            </li>
          );
        })}
      </ol>

      {/* Tablet and up: table. The featured model's columns come first and brightest, box score in
          the middle, and the other model's rank last, muted, as a comparison. */}
      <div className="hidden overflow-x-auto sm:block">
        <table className="w-full min-w-[720px] text-left">
          <thead>
            <tr className="border-b border-zinc-800">
              <th scope="col" className={`${TH} pl-0`}>Rank</th>
              <th scope="col" className={TH}>Player</th>
              {columns.map((c) => (
                <th
                  key={c.header}
                  scope="col"
                  className={[TH, "text-right", c.wideOnly && "hidden lg:table-cell", c.comparison && "border-l border-zinc-800 pr-0"]
                    .filter(Boolean).join(" ")}
                >
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {rows.map((r) => (
              <tr key={rowKey(r)} className="border-b border-zinc-900 last:border-0">
                <td className="py-5 pr-3 text-zinc-500">{rank(r) ?? DASH}</td>
                <td className="px-3 py-5">
                  <p className="text-lg font-medium text-zinc-100">{player(r)}</p>
                  <p className="mt-0.5 text-sm text-zinc-500">{teamCode(team(r)) ?? DASH}</p>
                </td>
                {columns.map((c) => (
                  <td
                    key={c.header}
                    className={[
                      "text-right",
                      c.comparison ? "border-l border-zinc-800 py-5 pl-3 text-zinc-500" : `px-3 py-5 ${TONE[c.tone ?? "stat"]}`,
                      c.wideOnly && "hidden lg:table-cell",
                    ].filter(Boolean).join(" ")}
                  >
                    {c.cell(r)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
