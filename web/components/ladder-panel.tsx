import type { Ladder } from "@/lib/ladder";
import { TeamLogo } from "@/components/team-logo";
import { formatDate, rank } from "@/lib/format";
import { teamCodeFromName } from "@/lib/teams";

/** "Official NBA MVP Ladder" side panel: NBA.com's Top 10 next to where our model ranks each player. */
export function LadderPanel({ ladder }: { ladder: Ladder | null }) {
  return (
    <aside aria-labelledby="nba-ladder" className="flex flex-col gap-4 rounded-2xl bg-panel p-5 ring-1 ring-line sm:p-6">
      <div className="flex flex-col gap-1">
        <h2 id="nba-ladder" className="text-lg font-semibold text-ink">Official NBA MVP Ladder</h2>
        {ladder ? (
          <p className="text-sm text-muted">
            {ladder.author ? `${ladder.author} · ` : ""}
            {formatDate(ladder.date)} ·{" "}
            <a href={ladder.url} target="_blank" rel="noopener noreferrer" className="font-medium text-brand hover:underline">
              NBA.com
            </a>
          </p>
        ) : (
          <p className="text-sm text-muted">The latest NBA.com ladder will appear after the next nightly update.</p>
        )}
      </div>

      {ladder && (
        <ol className="flex flex-col divide-y divide-line overflow-hidden rounded-xl bg-white ring-1 ring-line">
          <li className="flex items-center gap-3 px-4 py-2 text-xs font-medium uppercase tracking-[0.1em] text-muted">
            <span className="w-6">NBA</span>
            <span className="flex-1">Player</span>
            <span className="text-brand">Our model</span>
          </li>
          {ladder.entries.map((e) => {
            const diff = e.ourRank === null ? null : e.ladderRank - e.ourRank; // + = we rank them higher
            return (
              <li key={e.ladderRank} className="flex items-center gap-3 px-4 py-3">
                <span className="w-6 tabular-nums text-muted">{e.ladderRank}</span>
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold leading-snug text-ink">{e.player}</span>
                  <span className="mt-0.5 flex items-center gap-1.5 text-sm text-muted">
                    <TeamLogo team={teamCodeFromName(e.team)} size={14} />
                    {e.team}
                  </span>
                </span>
                <span className="text-right tabular-nums">
                  <span className="block font-semibold text-brand">{e.ourRank === null ? "—" : rank(e.ourRank)}</span>
                  <span className="block text-xs text-muted">
                    {e.ourRank === null ? "not ranked" : diff === 0 ? "same" : diff! > 0 ? `${diff} higher` : `${-diff!} lower`}
                  </span>
                </span>
              </li>
            );
          })}
        </ol>
      )}
      <p className="text-xs leading-relaxed text-muted">
        &quot;Not ranked&quot; = outside our model&apos;s MVP pool (minimum games, 15 PTS and 28 MPG). The ladder is
        NBA.com&apos;s editorial ranking; ours is Model 2&apos;s.
      </p>
    </aside>
  );
}
