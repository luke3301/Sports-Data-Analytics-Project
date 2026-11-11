import { LeaderCard, RacePage, RaceTable } from "@/components/race";
import { one, pct, rank, signed } from "@/lib/format";
import { getLatestPredictions, type Prediction } from "@/lib/predictions";

export default async function Home() {
  const day = await getLatestPredictions(10);
  const leader = day?.players[0];

  return (
    <RacePage
      title="NBA MVP Race"
      current="/"
      day={day}
      emptyText="No predictions yet. Check back after the next nightly update."
      footer={
        <>
          <p>
            Rankings come from <span className="text-zinc-400">Model 2</span>, a Random Forest + XGBoost ensemble built
            on modern stats including DARKO DPM and on/off impact. <span className="text-zinc-400">Vote Share</span> is
            its predicted fraction of MVP voting points.
          </p>
          <p>
            <span className="text-zinc-400">Dominance Score</span> measures statistical dominance with no ceiling: 35 is
            a typical rotation player, 82 an average MVP season, and 90+ historic.{" "}
            <span className="text-zinc-400">Model 1</span> (trained on MVP voting since 1980) is shown for comparison.
            Stats are season-to-date per game. Updated nightly; early in the season, small samples make rankings
            volatile.
          </p>
        </>
      }
    >
      {leader && (
        <LeaderCard
          badge="#1 · Projected MVP"
          player={leader.player}
          team={leader.team}
          stats={[
            { label: "Projected Vote Share", value: pct(leader.model2Share) },
            { label: "Dominance Score", value: one(leader.mvpIndex) },
            { label: "Points per game", value: one(leader.pts) },
            { label: "True Shooting", value: pct(leader.tsPct) },
            { label: "Box Plus/Minus", value: signed(leader.bpm) },
            { label: "Model 1 Rank", value: rank(leader.model1Rank) },
          ]}
        />
      )}
      {day && day.players.length > 1 && (
        <RaceTable<Prediction>
          title="The rest of the top 10"
          rows={day.players.slice(1)}
          rowKey={(p) => p.playerId}
          rank={(p) => p.model2Rank}
          player={(p) => p.player}
          team={(p) => p.team}
          columns={[
            { header: "Vote Share", cell: (p) => pct(p.model2Share), tone: "primary" },
            { header: "Dominance", cell: (p) => one(p.mvpIndex), tone: "primary" },
            { header: "PTS", cell: (p) => one(p.pts) },
            { header: "MPG", cell: (p) => one(p.mpg), tone: "muted", wideOnly: true },
            { header: "TS%", cell: (p) => pct(p.tsPct) },
            { header: "BPM", cell: (p) => signed(p.bpm) },
            { header: "VORP", cell: (p) => one(p.vorp), tone: "muted", wideOnly: true },
            { header: "Model 1", cell: (p) => rank(p.model1Rank), comparison: true },
          ]}
          mobileDetails={(p) => [`${one(p.pts)} PTS`, `${pct(p.tsPct)} TS`, `Model 1 ${rank(p.model1Rank)}`]}
          mobilePrimary={(p) => pct(p.model2Share)}
          mobileSecondary={(p) => `Dom ${one(p.mvpIndex)}`}
        />
      )}
    </RacePage>
  );
}
