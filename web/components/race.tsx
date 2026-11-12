import type { CSSProperties, ReactNode } from "react";
import { SiteNav, type NavHref } from "@/components/site-nav";
import { TeamLogo } from "@/components/team-logo";
import { TrendChart } from "@/components/trend-chart";
import { DASH, formatDate, int } from "@/lib/format";
import { GLOSSARY, GLOSSARY_ORDER } from "@/lib/glossary";
import type { Insight, RecentGame } from "@/lib/insights";
import { teamCode, teamName } from "@/lib/teams";
import type { Award } from "@/lib/trends";

// Shared layout for every award race page (MVP, ROY, DPOY): header + nav, a big #1 card, a list of the
// rest of the race where every row expands to show a performance summary and the last 3 games, and a
// methodology footer. Pages only supply data and column definitions, so all races look the same.
// Rows use native <details>/<summary>: no client JavaScript, keyboard accessible, server rendered.

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
    <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-10 px-5 py-10 sm:gap-14 sm:px-10 sm:py-14">
      <header className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex flex-col gap-1.5">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-brand">Live award race</p>
          <h1 className="text-3xl font-bold tracking-tight text-ink sm:text-4xl">{title}</h1>
          {day && (
            <p className="text-sm text-muted">
              {day.season} season · Updated {formatDate(day.date)}
            </p>
          )}
        </div>
        <SiteNav current={current} />
      </header>

      {day ? children : <p className="rounded-2xl bg-panel p-8 text-lg text-muted">{emptyText}</p>}

      <footer className="mt-auto flex flex-col gap-8 rounded-2xl bg-panel p-6 text-sm leading-relaxed text-muted sm:p-8">
        <div className="flex flex-col gap-3">{footer}</div>
        <Glossary />
      </footer>
    </main>
  );
}

// --------------------------------------------------------------------------- glossary + tooltips
function Glossary() {
  return (
    <section aria-labelledby="glossary" className="flex flex-col gap-4 border-t border-line pt-6">
      <h2 id="glossary" className="text-base font-semibold text-ink">Glossary</h2>
      <dl className="grid gap-x-8 gap-y-4 md:grid-cols-2">
        {GLOSSARY_ORDER.map((key) => (
          <div key={key} className="flex flex-col gap-1">
            <dt className="font-semibold text-ink">{GLOSSARY[key].term}</dt>
            <dd>{GLOSSARY[key].definition}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** Column header with a hover/focus tooltip from the glossary (plain text header if no entry). */
function HeaderTip({ label }: { label: string }) {
  const entry = GLOSSARY[label];
  if (!entry) return <>{label}</>;
  const id = `tip-${label.replace(/[^A-Za-z0-9]/g, "")}`;
  return (
    <span tabIndex={0} aria-describedby={id}
          className="group/tip relative inline-flex cursor-help items-center gap-1 rounded outline-none focus-visible:ring-2 focus-visible:ring-brand">
      {label}
      <svg viewBox="0 0 16 16" aria-hidden="true" className="h-3 w-3 opacity-60">
        <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
        <path d="M8 7v4M8 4.8v.1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      <span role="tooltip" id={id}
            className="pointer-events-none invisible absolute right-0 top-full z-20 mt-2 w-64 whitespace-normal rounded-lg bg-ink px-3 py-2.5 text-left text-xs font-normal normal-case leading-relaxed tracking-normal text-white opacity-0 shadow-lg transition-opacity group-hover/tip:visible group-hover/tip:opacity-100 group-focus-visible/tip:visible group-focus-visible/tip:opacity-100">
        <span className="mb-0.5 block font-semibold">{entry.term}</span>
        {entry.definition}
      </span>
    </span>
  );
}

// --------------------------------------------------------------------------- small pieces
/** ▲2 / ▼1 since the previous day; nothing when unknown. */
export function Movement({ change, onBrand = false }: { change: number | null; onBrand?: boolean }) {
  if (change === null || change === 0) return null;
  const up = change > 0;
  const tone = onBrand ? "bg-white/15 text-white" : up ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700";
  return (
    <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-xs font-semibold tabular-nums ${tone}`}
          title={`${up ? "Up" : "Down"} ${Math.abs(change)} since the previous update`}>
      {up ? "▲" : "▼"}
      {Math.abs(change)}
    </span>
  );
}

function Chevron() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true" className="h-4 w-4 shrink-0 text-muted transition-transform group-open:rotate-180">
      <path d="M5 7.5l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const fg = (v: number | null) => (v === null ? DASH : `${(v * 100).toFixed(0)}%`);
const gameDate = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });

function RecentGames({ games, onBrand }: { games: RecentGame[]; onBrand: boolean }) {
  const head = onBrand ? "text-white/70" : "text-muted";
  const cell = onBrand ? "text-white" : "text-ink";
  const rule = onBrand ? "border-white/15" : "border-line";
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[26rem] text-left text-sm tabular-nums">
        <thead>
          <tr className={`border-b ${rule} text-xs uppercase tracking-[0.1em] ${head}`}>
            <th scope="col" className="py-2 pr-3 font-medium">Game</th>
            {["PTS", "REB", "AST", "STL", "BLK", "FG%"].map((h) => (
              <th key={h} scope="col" className="px-2 py-2 text-right font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {[...games].reverse().map((g) => (
            <tr key={g.date} className={`border-b ${rule} last:border-0`}>
              <td className={`py-2 pr-3 ${cell}`}>
                <span className="font-medium">{gameDate(g.date)}</span>
                <span className={head}> {g.home ? "vs" : "@"} {teamCode(g.opp)}</span>
                {g.result && <span className={`ml-1.5 ${head}`}>{g.result.split(",")[0]}</span>}
              </td>
              {[g.pts, g.reb, g.ast, g.stl, g.blk].map((v, i) => (
                <td key={i} className={`px-2 py-2 text-right ${cell}`}>{int(v)}</td>
              ))}
              <td className={`px-2 py-2 text-right ${cell}`}>{fg(g.fg_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Expanded content: performance summary, last 3 games and the season trend (placeholders until the
 *  nightly run fills them in). */
export function InsightPanel({ insight, seasonLine, award, playerId, onBrand = false }: {
  insight: Insight; seasonLine?: string; award: Award; playerId: string; onBrand?: boolean;
}) {
  const label = `text-xs font-semibold uppercase tracking-[0.14em] ${onBrand ? "text-white/70" : "text-muted"}`;
  const body = onBrand ? "text-white" : "text-ink";
  const empty = onBrand ? "text-white/70" : "text-muted";
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
      <div className="flex min-w-0 flex-col gap-2">
        <h3 className={label}>Performance Summary</h3>
        <p className={`leading-relaxed ${insight.summary ? body : empty}`}>
          {insight.summary ?? "A performance summary will appear after the next nightly update."}
        </p>
        {seasonLine && <p className={`text-sm ${empty}`}>Season: {seasonLine}</p>}
      </div>
      <div className="flex min-w-0 flex-col gap-2">
        <h3 className={label}>Recent Games (Last 3)</h3>
        {insight.recentGames.length ? (
          <RecentGames games={insight.recentGames} onBrand={onBrand} />
        ) : (
          <p className={empty}>Recent games will appear after the next nightly update.</p>
        )}
      </div>
      <div className="flex min-w-0 flex-col gap-2 lg:col-span-2">
        <h3 className={label}>Vote Share Trend (This Season)</h3>
        <TrendChart award={award} playerId={playerId} onBrand={onBrand} />
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- #1 card
export type StatItem = { label: string; value: string; note?: string };

export function LeaderCard({
  badge, badgeShort, player, playerId, award, team, stats, insight, seasonLine,
}: {
  badge: string; // e.g. "#1 · Projected MVP"
  badgeShort?: string; // shown on phones when the full badge would wrap
  player: string;
  playerId: string;
  award: Award;
  team: string | null;
  stats: StatItem[];
  insight: Insight;
  seasonLine?: string;
}) {
  return (
    <section aria-labelledby="leader-name"
             className="rounded-2xl bg-brand p-7 text-white shadow-[0_18px_40px_-18px_rgba(31,107,255,0.55)] sm:p-10 lg:p-12">
      <div className="flex flex-wrap items-center gap-2">
        <p className="inline-flex items-center rounded-full bg-white px-3.5 py-1.5 text-xs font-bold uppercase tracking-[0.16em] text-brand">
          {badgeShort ? (
            <>
              <span className="sm:hidden">{badgeShort}</span>
              <span className="hidden sm:inline">{badge}</span>
            </>
          ) : (
            badge
          )}
        </p>
        <Movement change={insight.rankChange} onBrand />
      </div>
      <h2 id="leader-name" className="mt-6 text-4xl font-bold tracking-tight [overflow-wrap:anywhere] min-[400px]:text-5xl sm:text-6xl lg:text-7xl">
        {player}
      </h2>
      <p className="mt-3 flex items-center gap-2.5 text-lg text-white/85">
        <TeamLogo team={team} size={22} chip />
        {teamName(team)}
      </p>

      <dl className="mt-10 grid grid-cols-2 gap-x-6 gap-y-6 sm:grid-cols-3">
        {stats.map((s) => (
          <div key={s.label} className="flex flex-col gap-1.5 rounded-xl bg-white/10 px-4 py-3.5">
            <dt className="text-xs font-medium uppercase tracking-[0.12em] text-white/70">{s.label}</dt>
            <dd className="text-2xl font-semibold tabular-nums sm:text-3xl">
              {s.value}
              {s.note && <span className="ml-1.5 text-sm font-normal text-white/70">{s.note}</span>}
            </dd>
          </div>
        ))}
      </dl>

      <details className="group mt-8 rounded-xl bg-white/10">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-semibold [&::-webkit-details-marker]:hidden">
          Recent games &amp; performance summary
          <svg viewBox="0 0 20 20" aria-hidden="true" className="h-4 w-4 transition-transform group-open:rotate-180">
            <path d="M5 7.5l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </summary>
        <div className="px-4 pb-5 pt-1">
          <InsightPanel insight={insight} seasonLine={seasonLine} award={award} playerId={playerId} onBrand />
        </div>
      </details>
    </section>
  );
}

// --------------------------------------------------------------------------- rest of the race
export type Column<T> = {
  header: string;
  cell: (row: T) => string;
  /** primary = the featured model's numbers (bold); stat = box score; muted = secondary */
  tone?: "primary" | "stat" | "muted";
  /** hidden on tablets, shown from laptop width */
  wideOnly?: boolean;
  /** a comparison column (other model / NBA.com), set off by a divider */
  comparison?: boolean;
  /** column width (default 4.4rem); widen for long headers such as "Vote Share" */
  width?: string;
};

const TONE = { primary: "font-semibold text-ink", stat: "text-ink/80", muted: "text-muted" };
const COL_W = "4.4rem";

function template<T>(columns: Column<T>[], includeWide: boolean) {
  const cols = columns.filter((c) => includeWide || !c.wideOnly).map((c) => c.width ?? COL_W);
  return ["2.25rem", "minmax(0,1fr)", ...cols, "1.25rem"].join(" ");
}

export function RaceTable<T>({
  title, award, rows, rowKey, rank, player, team, columns, mobileDetails, mobilePrimary, mobileSecondary,
  insight, seasonLine,
}: {
  title: string;
  award: Award;
  rows: T[];
  rowKey: (r: T) => string; // the player id (also used for the trend chart)
  rank: (r: T) => number | null;
  player: (r: T) => string;
  team: (r: T) => string | null;
  columns: Column<T>[];
  /** phone rows: small pieces under the name (team is added first), each kept on one line */
  mobileDetails: (r: T) => string[];
  mobilePrimary: (r: T) => string;
  mobileSecondary: (r: T) => string;
  insight: (r: T) => Insight;
  seasonLine?: (r: T) => string;
}) {
  const grid = {
    "--cols": template(columns, false),
    "--cols-wide": template(columns, true),
  } as CSSProperties;
  const gridClass = "grid items-center gap-x-2 [grid-template-columns:var(--cols)] lg:[grid-template-columns:var(--cols-wide)]";

  return (
    <section aria-labelledby="contenders" className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="contenders" className="text-lg font-semibold text-ink">{title}</h2>
        <p className="text-sm text-muted">Select a player for recent games</p>
      </div>

      <div className="rounded-2xl bg-panel ring-1 ring-line [&>details:last-child]:rounded-b-2xl">
        {/* column headers (tablet and up) */}
        <div style={grid} className={`${gridClass} hidden border-b border-line px-5 py-3 text-xs font-medium uppercase tracking-[0.1em] text-muted sm:grid`}>
          <span>Rank</span>
          <span>Player</span>
          {columns.map((c) => (
            <span key={c.header}
                  className={`whitespace-nowrap text-right ${c.wideOnly ? "hidden lg:block" : ""} ${c.comparison ? "text-brand" : ""}`}>
              <HeaderTip label={c.header} />
            </span>
          ))}
          <span />
        </div>

        {rows.map((r) => {
          const ins = insight(r);
          const details = [teamCode(team(r)) ?? DASH, ...mobileDetails(r)];
          return (
            <details key={rowKey(r)} className="group border-b border-line last:border-0 open:bg-white">
              <summary className="cursor-pointer list-none px-4 py-4 transition-colors hover:bg-white sm:px-5 [&::-webkit-details-marker]:hidden">
                {/* phones */}
                <div className="flex items-center gap-3 sm:hidden">
                  <span className="w-6 shrink-0 tabular-nums text-muted">{rank(r) ?? DASH}</span>
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-2">
                      <span className="min-w-0 break-words text-base font-semibold text-ink">{player(r)}</span>
                      <Movement change={ins.rankChange} />
                    </p>
                    <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-sm tabular-nums text-muted">
                      <TeamLogo team={team(r)} size={14} />
                      {details.map((d, i) => (
                        <span key={i} className="whitespace-nowrap">{i < details.length - 1 ? `${d} ·` : d}</span>
                      ))}
                    </p>
                  </div>
                  <div className="shrink-0 text-right tabular-nums">
                    <p className="text-base font-semibold text-ink">{mobilePrimary(r)}</p>
                    <p className="mt-0.5 text-sm text-muted">{mobileSecondary(r)}</p>
                  </div>
                  <Chevron />
                </div>
                {/* tablet and up */}
                <div style={grid} className={`${gridClass} hidden tabular-nums sm:grid`}>
                  <span className="text-muted">{rank(r) ?? DASH}</span>
                  <span className="min-w-0">
                    <span className="flex items-center gap-2">
                      <span className="min-w-0 break-words text-base font-semibold text-ink">{player(r)}</span>
                      <Movement change={ins.rankChange} />
                    </span>
                    <span className="mt-1 flex items-center gap-1.5 text-sm text-muted">
                      <TeamLogo team={team(r)} size={16} />
                      {teamCode(team(r)) ?? DASH}
                    </span>
                  </span>
                  {columns.map((c) => (
                    <span key={c.header}
                          className={`text-right ${c.comparison ? "text-brand" : TONE[c.tone ?? "stat"]} ${c.wideOnly ? "hidden lg:block" : ""}`}>
                      {c.cell(r)}
                    </span>
                  ))}
                  <Chevron />
                </div>
              </summary>
              <div className="px-4 pb-6 pt-1 sm:px-5 sm:pl-[3.4rem]">
                <InsightPanel insight={ins} seasonLine={seasonLine?.(r)} award={award} playerId={rowKey(r)} />
              </div>
            </details>
          );
        })}
      </div>
    </section>
  );
}
