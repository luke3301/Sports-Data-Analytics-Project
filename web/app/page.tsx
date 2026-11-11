import { SiteNav } from "@/components/site-nav";
import { getLatestPredictions, type Prediction } from "@/lib/predictions";

const TEAM_NAMES: Record<string, string> = {
  ATL: "Atlanta Hawks", BOS: "Boston Celtics", BKN: "Brooklyn Nets", CHA: "Charlotte Hornets",
  CHI: "Chicago Bulls", CLE: "Cleveland Cavaliers", DAL: "Dallas Mavericks", DEN: "Denver Nuggets",
  DET: "Detroit Pistons", GSW: "Golden State Warriors", HOU: "Houston Rockets", IND: "Indiana Pacers",
  LAC: "LA Clippers", LAL: "Los Angeles Lakers", MEM: "Memphis Grizzlies", MIA: "Miami Heat",
  MIL: "Milwaukee Bucks", MIN: "Minnesota Timberwolves", NOP: "New Orleans Pelicans", NYK: "New York Knicks",
  OKC: "Oklahoma City Thunder", ORL: "Orlando Magic", PHI: "Philadelphia 76ers", PHX: "Phoenix Suns",
  POR: "Portland Trail Blazers", SAC: "Sacramento Kings", SAS: "San Antonio Spurs", TOR: "Toronto Raptors",
  UTA: "Utah Jazz", WAS: "Washington Wizards",
};

const DASH = "—";
const one = (v: number | null) => (v === null ? DASH : v.toFixed(1));
const signed = (v: number | null) => (v === null ? DASH : `${v > 0 ? "+" : ""}${v.toFixed(1)}`);
const pct = (v: number | null) => (v === null ? DASH : `${(v * 100).toFixed(1)}%`);
const rank = (v: number | null) => (v === null ? DASH : `#${v}`);
const teamName = (abbr: string | null) => (abbr ? (TEAM_NAMES[abbr] ?? abbr) : "");

function formatDate(isoDate: string) {
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString("en-US", {
    timeZone: "UTC", month: "long", day: "numeric", year: "numeric",
  });
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
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

function Leader({ leader }: { leader: Prediction }) {
  return (
    <section aria-labelledby="leader-name" className="rounded-3xl border border-zinc-800 bg-zinc-900/40 p-8 sm:p-12 lg:p-16">
      <p className="inline-flex items-center rounded-full bg-amber-400 px-4 py-1.5 text-xs font-bold uppercase tracking-[0.18em] text-zinc-950">
        #1 · Projected MVP
      </p>
      <h1 id="leader-name" className="mt-8 text-4xl font-bold tracking-tight [overflow-wrap:anywhere] text-zinc-50 min-[400px]:text-5xl sm:text-7xl lg:text-8xl">
        {leader.player}
      </h1>
      <p className="mt-4 text-lg text-zinc-400 sm:text-xl">{teamName(leader.team)}</p>

      <dl className="mt-12 grid grid-cols-2 gap-x-8 gap-y-10 border-t border-zinc-800 pt-10 sm:mt-16 sm:grid-cols-3">
        <Stat label="Projected Vote Share" value={pct(leader.model2Share)} />
        <Stat label="Dominance Score" value={one(leader.mvpIndex)} />
        <Stat label="Points per game" value={one(leader.pts)} />
        <Stat label="True Shooting" value={pct(leader.tsPct)} />
        <Stat label="Box Plus/Minus" value={signed(leader.bpm)} />
        <Stat label="Model 1 Rank" value={rank(leader.model1Rank)} />
      </dl>
    </section>
  );
}

const TH = "whitespace-nowrap py-4 px-3 text-xs font-medium uppercase tracking-[0.12em] text-zinc-500";

function Contenders({ players }: { players: Prediction[] }) {
  return (
    <section aria-labelledby="contenders" className="flex flex-col gap-6">
      <h2 id="contenders" className="text-sm font-medium uppercase tracking-[0.14em] text-zinc-500">
        The rest of the top 10
      </h2>

      {/* Phones: stacked rows, so the key numbers are visible without sideways scrolling */}
      <ol className="flex flex-col sm:hidden">
        {players.map((p) => (
          <li key={p.playerId} className="flex items-center gap-4 border-b border-zinc-900 py-5 last:border-0">
            <span className="w-6 shrink-0 tabular-nums text-zinc-500">{p.model2Rank ?? DASH}</span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-lg font-medium text-zinc-100">{p.player}</p>
              {/* each piece stays on one line; wrapping only happens between pieces */}
              <p className="mt-1 flex flex-wrap gap-x-1.5 text-sm tabular-nums text-zinc-500">
                <span className="whitespace-nowrap">{p.team ?? DASH} ·</span>
                <span className="whitespace-nowrap">{one(p.pts)} PTS ·</span>
                <span className="whitespace-nowrap">{pct(p.tsPct)} TS ·</span>
                <span className="whitespace-nowrap">Model 1 {rank(p.model1Rank)}</span>
              </p>
            </div>
            <div className="shrink-0 text-right tabular-nums">
              <p className="text-lg text-zinc-100">{pct(p.model2Share)}</p>
              <p className="mt-1 text-sm text-zinc-500">Dom {one(p.mvpIndex)}</p>
            </div>
          </li>
        ))}
      </ol>

      {/* Tablet and up: table. Model 2 columns first and brightest; box score in the middle;
          Model 1 rank last, muted, as a comparison. MPG and VORP appear from laptop width up. */}
      <div className="hidden overflow-x-auto sm:block">
        <table className="w-full min-w-[720px] text-left">
          <thead>
            <tr className="border-b border-zinc-800">
              <th scope="col" className={`${TH} pl-0`}>Rank</th>
              <th scope="col" className={TH}>Player</th>
              <th scope="col" className={`${TH} text-right`}>Vote Share</th>
              <th scope="col" className={`${TH} text-right`}>Dominance</th>
              <th scope="col" className={`${TH} text-right`}>PTS</th>
              <th scope="col" className={`${TH} hidden text-right lg:table-cell`}>MPG</th>
              <th scope="col" className={`${TH} text-right`}>TS%</th>
              <th scope="col" className={`${TH} text-right`}>BPM</th>
              <th scope="col" className={`${TH} hidden text-right lg:table-cell`}>VORP</th>
              <th scope="col" className={`${TH} border-l border-zinc-800 pr-0 text-right`}>Model 1</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {players.map((p) => (
              <tr key={p.playerId} className="border-b border-zinc-900 last:border-0">
                <td className="py-5 pr-3 text-zinc-500">{p.model2Rank ?? DASH}</td>
                <td className="px-3 py-5">
                  <p className="text-lg font-medium text-zinc-100">{p.player}</p>
                  <p className="mt-0.5 text-sm text-zinc-500">{p.team ?? DASH}</p>
                </td>
                <td className="px-3 py-5 text-right text-lg text-zinc-100">{pct(p.model2Share)}</td>
                <td className="px-3 py-5 text-right text-lg text-zinc-100">{one(p.mvpIndex)}</td>
                <td className="px-3 py-5 text-right text-zinc-300">{one(p.pts)}</td>
                <td className="hidden px-3 py-5 text-right text-zinc-400 lg:table-cell">{one(p.mpg)}</td>
                <td className="px-3 py-5 text-right text-zinc-300">{pct(p.tsPct)}</td>
                <td className="px-3 py-5 text-right text-zinc-300">{signed(p.bpm)}</td>
                <td className="hidden px-3 py-5 text-right text-zinc-400 lg:table-cell">{one(p.vorp)}</td>
                <td className="border-l border-zinc-800 py-5 pl-3 text-right text-zinc-500">{rank(p.model1Rank)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default async function Home() {
  const day = await getLatestPredictions(10);

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-16 px-6 py-12 sm:gap-20 sm:px-10 sm:py-20">
      <header className="flex flex-col gap-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-baseline sm:justify-between">
          <p className="text-sm font-bold uppercase tracking-[0.2em] text-amber-400">NBA MVP Race</p>
          <SiteNav current="/" />
        </div>
        {day && (
          <p className="text-sm text-zinc-500">
            {day.season} season · Updated {formatDate(day.date)}
          </p>
        )}
      </header>

      {day ? (
        <>
          <Leader leader={day.players[0]} />
          {day.players.length > 1 && <Contenders players={day.players.slice(1)} />}
        </>
      ) : (
        <p className="text-lg text-zinc-400">No predictions yet. Check back after the next nightly update.</p>
      )}

      <footer className="mt-auto flex flex-col gap-3 border-t border-zinc-900 pt-8 text-sm leading-relaxed text-zinc-500">
        <p>
          Rankings come from <span className="text-zinc-400">Model 2</span>, a Random Forest + XGBoost ensemble built on
          modern stats including DARKO DPM and on/off impact. <span className="text-zinc-400">Vote Share</span> is its
          predicted fraction of MVP voting points.
        </p>
        <p>
          <span className="text-zinc-400">Dominance Score</span> measures statistical dominance with no ceiling: 35 is a
          typical rotation player, 82 an average MVP season, and 90+ historic.{" "}
          <span className="text-zinc-400">Model 1</span> (trained on MVP voting since 1980) is shown for comparison.
          Stats are season-to-date per game. Updated nightly; early in the season, small samples make rankings volatile.
        </p>
      </footer>
    </main>
  );
}
