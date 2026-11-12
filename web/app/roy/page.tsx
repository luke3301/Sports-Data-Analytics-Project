import type { Metadata } from "next";
import { LeaderCard, RacePage, RaceTable } from "@/components/race";
import { int, one, pct, rank, signed } from "@/lib/format";
import { getLatestRoy, type RookiePrediction } from "@/lib/roy";

export const metadata: Metadata = {
  title: "Rookie of the Year Race · Live Predictions",
  description: "Who is the NBA Rookie of the Year right now? Daily machine-learning predictions of the rookie class.",
};

const pick = (v: number | null) => (v === null ? "Undrafted" : `#${v}`);
const seasonLine = (p: RookiePrediction) =>
  `${one(p.pts)} PTS · ${one(p.reb)} REB · ${one(p.ast)} AST · ${one(p.mpg)} MPG · ${int(p.games)} GP · ${pct(p.tsPct)} TS · ${signed(p.bpm)} BPM · pick ${pick(p.draftPick)}`;

export default async function RoyPage() {
  const day = await getLatestRoy(5);
  const leader = day?.players[0];

  return (
    <RacePage
      title="Rookie of the Year Race"
      current="/roy"
      day={day}
      emptyText="No rookie predictions yet. Check back after the next nightly update."
      footer={
        <>
          <p>
            Rankings come from <span className="font-medium text-ink">Model 1 (Traditional Voter)</span>, trained on Rookie of
            the Year voting since 1980 using what voters reward most: scoring, minutes, games played and draft slot.{" "}
            <span className="font-medium text-ink">Vote Share</span> is its predicted fraction of ROY voting points.
          </p>
          <p>
            <span className="font-medium text-ink">Model 2 (Combined Impact)</span> adds efficiency and team success (BPM and
            team win %) and is shown for comparison. Rookies must have played at least half the season&apos;s games.
            Stats are season-to-date per game. Updated nightly; early in the season, small samples make rankings
            volatile.
          </p>
        </>
      }
    >
      {leader && (
        <LeaderCard
          badge="#1 · Projected Rookie of the Year"
          badgeShort="#1 · Projected ROY"
          player={leader.player}
          playerId={leader.playerId}
          award="roy"
          team={leader.team}
          insight={leader.insight}
          seasonLine={seasonLine(leader)}
          stats={[
            { label: "Projected Vote Share", value: pct(leader.model1Share) },
            { label: "Traditional Score", value: one(leader.model1Score) },
            { label: "Points per game", value: one(leader.pts) },
            { label: "Draft Pick", value: pick(leader.draftPick) },
            { label: "Games Played", value: int(leader.games) },
            { label: "Model 2 Rank", value: rank(leader.model2Rank) },
          ]}
        />
      )}
      {day && day.players.length > 1 && (
        <RaceTable<RookiePrediction>
          title="The rest of the top 5"
          award="roy"
          rows={day.players.slice(1)}
          rowKey={(p) => p.playerId}
          rank={(p) => p.model1Rank}
          player={(p) => p.player}
          team={(p) => p.team}
          insight={(p) => p.insight}
          seasonLine={seasonLine}
          columns={[
            { header: "Vote Share", width: "5.6rem", cell: (p) => pct(p.model1Share), tone: "primary" },
            { header: "Score", cell: (p) => one(p.model1Score), tone: "primary" },
            { header: "PTS", cell: (p) => one(p.pts) },
            { header: "MPG", cell: (p) => one(p.mpg), tone: "muted", wideOnly: true },
            { header: "TS%", cell: (p) => pct(p.tsPct) },
            { header: "BPM", cell: (p) => signed(p.bpm) },
            { header: "Pick", cell: (p) => pick(p.draftPick), tone: "muted", wideOnly: true },
            { header: "Model 2", cell: (p) => rank(p.model2Rank), comparison: true },
          ]}
          mobileDetails={(p) => [`${one(p.pts)} PTS`, `Pick ${pick(p.draftPick)}`, `Model 2 ${rank(p.model2Rank)}`]}
          mobilePrimary={(p) => pct(p.model1Share)}
          mobileSecondary={(p) => `Score ${one(p.model1Score)}`}
        />
      )}
    </RacePage>
  );
}
