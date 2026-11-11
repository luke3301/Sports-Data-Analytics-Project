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

const score = (v: number | null) => (v === null ? "—" : v.toFixed(1));
const share = (v: number | null) => (v === null ? "—" : `${(v * 100).toFixed(1)}%`);
const rank = (v: number | null) => (v === null ? "—" : `#${v}`);
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

function Leader({ leader, runnerUp }: { leader: Prediction; runnerUp?: Prediction }) {
  const lead =
    runnerUp && leader.model1Score !== null && runnerUp.model1Score !== null
      ? leader.model1Score - runnerUp.model1Score
      : null;

  return (
    <section aria-labelledby="leader-name" className="rounded-3xl border border-zinc-800 bg-zinc-900/40 p-8 sm:p-12 lg:p-16">
      <p className="inline-flex items-center rounded-full bg-amber-400 px-4 py-1.5 text-xs font-bold uppercase tracking-[0.18em] text-zinc-950">
        #1 · Projected MVP
      </p>
      <h1 id="leader-name" className="mt-8 text-5xl font-bold tracking-tight text-zinc-50 sm:text-7xl lg:text-8xl">
        {leader.player}
      </h1>
      <p className="mt-4 text-lg text-zinc-400 sm:text-xl">{teamName(leader.team)}</p>

      <dl className="mt-12 grid grid-cols-2 gap-x-8 gap-y-10 border-t border-zinc-800 pt-10 sm:mt-16 lg:grid-cols-4">
        <Stat label="Model 1 Score" value={score(leader.model1Score)} note="/ 100" />
        <Stat label="Model 1 Share" value={share(leader.model1Share)} />
        <Stat label="Model 2 Rank" value={rank(leader.model2Rank)} />
        <Stat label="Lead over #2" value={lead === null ? "—" : `+${lead.toFixed(1)}`} note="pts" />
      </dl>
    </section>
  );
}

function Contenders({ players }: { players: Prediction[] }) {
  return (
    <section aria-labelledby="contenders" className="flex flex-col gap-6">
      <h2 id="contenders" className="text-sm font-medium uppercase tracking-[0.14em] text-zinc-500">
        The rest of the top 10
      </h2>
      {/* Phones: stacked rows, so every value is visible without sideways scrolling */}
      <ol className="flex flex-col sm:hidden">
        {players.map((p) => (
          <li key={p.playerId} className="flex items-center gap-4 border-b border-zinc-900 py-5 last:border-0">
            <span className="w-6 shrink-0 tabular-nums text-zinc-500">{p.model1Rank ?? "—"}</span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-lg font-medium text-zinc-100">{p.player}</p>
              <p className="mt-1 text-sm text-zinc-500">
                {p.team ?? "—"} · Model 2 {rank(p.model2Rank)}
              </p>
            </div>
            <div className="shrink-0 text-right tabular-nums">
              <p className="text-lg text-zinc-100">{score(p.model1Score)}</p>
              <p className="mt-1 text-sm text-zinc-500">{share(p.model1Share)}</p>
            </div>
          </li>
        ))}
      </ol>

      {/* Tablet and up: full table */}
      <div className="hidden overflow-x-auto sm:block">
        <table className="w-full min-w-[640px] text-left">
          <thead>
            <tr className="border-b border-zinc-800 text-xs uppercase tracking-[0.12em] text-zinc-500">
              <th scope="col" className="py-4 pr-6 font-medium">Rank</th>
              <th scope="col" className="py-4 pr-6 font-medium">Player</th>
              <th scope="col" className="py-4 pr-6 font-medium">Team</th>
              <th scope="col" className="py-4 pr-6 text-right font-medium">Model 1 Score</th>
              <th scope="col" className="py-4 pr-6 text-right font-medium">Model 1 Share</th>
              <th scope="col" className="py-4 text-right font-medium">Model 2 Rank</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {players.map((p) => (
              <tr key={p.playerId} className="border-b border-zinc-900 last:border-0">
                <td className="py-5 pr-6 text-zinc-500">{p.model1Rank ?? "—"}</td>
                <td className="py-5 pr-6 text-lg font-medium text-zinc-100">{p.player}</td>
                <td className="py-5 pr-6 text-zinc-400">{p.team ?? "—"}</td>
                <td className="py-5 pr-6 text-right text-zinc-100">{score(p.model1Score)}</td>
                <td className="py-5 pr-6 text-right text-zinc-300">{share(p.model1Share)}</td>
                <td className="py-5 text-right text-zinc-400">{rank(p.model2Rank)}</td>
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
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-16 px-6 py-12 sm:gap-20 sm:px-10 sm:py-20">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-baseline sm:justify-between">
        <p className="text-sm font-bold uppercase tracking-[0.2em] text-amber-400">NBA MVP Race</p>
        {day && (
          <p className="text-sm text-zinc-500">
            {day.season} season · Updated {formatDate(day.date)}
          </p>
        )}
      </header>

      {day ? (
        <>
          <Leader leader={day.players[0]} runnerUp={day.players[1]} />
          {day.players.length > 1 && <Contenders players={day.players.slice(1)} />}
        </>
      ) : (
        <p className="text-lg text-zinc-400">No predictions yet. Check back after the next nightly update.</p>
      )}

      <footer className="mt-auto border-t border-zinc-900 pt-8 text-sm leading-relaxed text-zinc-500">
        <p>
          <span className="text-zinc-400">Model 1</span> blends a linear model with XGBoost, trained on MVP voting since
          1980; its score runs 0–100. <span className="text-zinc-400">Model 2</span> is a Random Forest + XGBoost
          ensemble built on modern stats, including DARKO DPM and on/off impact. Shares are each model&apos;s predicted
          fraction of MVP voting points. Updated nightly. Early in the season, small samples make rankings volatile.
        </p>
      </footer>
    </main>
  );
}
