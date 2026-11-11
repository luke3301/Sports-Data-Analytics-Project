import type { Metadata } from "next";
import { LeaderCard, RacePage, RaceTable } from "@/components/race";
import { getLatestDpoy, type DefenderPrediction } from "@/lib/dpoy";
import { one, pct, rank, signed } from "@/lib/format";

export const metadata: Metadata = {
  title: "Defensive Player of the Year Race · Live Predictions",
  description: "Who is the NBA Defensive Player of the Year right now? Daily machine-learning predictions.",
};

export default async function DpoyPage() {
  const day = await getLatestDpoy(10);
  const leader = day?.players[0];

  return (
    <RacePage
      title="Defensive Player of the Year Race"
      current="/dpoy"
      day={day}
      emptyText="No DPOY predictions yet. Check back after the next nightly update."
      footer={
        <>
          <p>
            Rankings come from <span className="text-zinc-400">Model 1 (Traditional Voter)</span>, trained on DPOY
            voting since 1983 using what voters reward: reputation (last season&apos;s DPOY votes), anchoring a top-5
            team defense, and blocks, steals and rebounds. <span className="text-zinc-400">Vote Share</span> is its
            predicted fraction of DPOY voting points.
          </p>
          <p>
            <span className="text-zinc-400">Model 2 (Advanced Impact)</span> looks for the most impactful defender by
            defensive box plus/minus, defensive win shares and block, steal and rebound rates, and is shown for
            comparison. Candidates must meet a pro-rated version of the NBA&apos;s 65-game rule and play 20+ minutes per
            game. Updated nightly; early in the season, small samples make rankings volatile.
          </p>
        </>
      }
    >
      {leader && (
        <LeaderCard
          badge="#1 · Projected Defensive Player of the Year"
          badgeShort="#1 · Projected DPOY"
          player={leader.player}
          team={leader.team}
          stats={[
            { label: "Projected Vote Share", value: pct(leader.model1Share) },
            { label: "Traditional Score", value: one(leader.model1Score) },
            { label: "Blocks per game", value: one(leader.blk) },
            { label: "Steals per game", value: one(leader.stl) },
            { label: "Team Defense Rank", value: rank(leader.teamDrtgRank) },
            { label: "Model 2 Rank", value: rank(leader.model2Rank) },
          ]}
        />
      )}
      {day && day.players.length > 1 && (
        <RaceTable<DefenderPrediction>
          title="The rest of the top 10"
          rows={day.players.slice(1)}
          rowKey={(p) => p.playerId}
          rank={(p) => p.model1Rank}
          player={(p) => p.player}
          team={(p) => p.team}
          columns={[
            { header: "Vote Share", cell: (p) => pct(p.model1Share), tone: "primary" },
            { header: "Score", cell: (p) => one(p.model1Score), tone: "primary" },
            { header: "BLK", cell: (p) => one(p.blk) },
            { header: "STL", cell: (p) => one(p.stl) },
            { header: "REB", cell: (p) => one(p.reb), tone: "muted", wideOnly: true },
            { header: "DBPM", cell: (p) => signed(p.dbpm) },
            { header: "Team D", cell: (p) => rank(p.teamDrtgRank), tone: "muted", wideOnly: true },
            { header: "Model 2", cell: (p) => rank(p.model2Rank), comparison: true },
          ]}
          mobileDetails={(p) => [`${one(p.blk)} BLK`, `${one(p.stl)} STL`, `Model 2 ${rank(p.model2Rank)}`]}
          mobilePrimary={(p) => pct(p.model1Share)}
          mobileSecondary={(p) => `Score ${one(p.model1Score)}`}
        />
      )}
    </RacePage>
  );
}
