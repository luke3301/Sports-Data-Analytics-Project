import { LadderPanel } from "@/components/ladder-panel";
import { LeaderCard, RacePage, RaceTable } from "@/components/race";
import { one, pct, rank, signed } from "@/lib/format";
import { getLatestLadder } from "@/lib/ladder";
import { getLatestPredictions, type Prediction } from "@/lib/predictions";

const seasonLine = (p: Prediction) =>
  `${one(p.pts)} PTS · ${one(p.reb)} REB · ${one(p.ast)} AST · ${one(p.mpg)} MPG · ${pct(p.tsPct)} TS · ${signed(p.bpm)} BPM · ${one(p.vorp)} VORP`;

export default async function Home() {
  const [day, ladder] = await Promise.all([getLatestPredictions(10), getLatestLadder()]);
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
            Rankings come from <span className="font-medium text-ink">Model 2</span>, a Random Forest + XGBoost
            ensemble built on modern stats including DARKO DPM and on/off impact.{" "}
            <span className="font-medium text-ink">Vote Share</span> is its predicted fraction of MVP voting points.
          </p>
          <p>
            <span className="font-medium text-ink">Dominance Score</span> measures statistical dominance with no
            ceiling: 35 is a typical rotation player, 82 an average MVP season, and 90+ historic.{" "}
            <span className="font-medium text-ink">Model 1</span> (trained on MVP voting since 1980) and the official{" "}
            <span className="font-medium text-ink">NBA.com Kia MVP Ladder</span> are shown for comparison. Stats are
            season-to-date per game. Updated nightly; early in the season, small samples make rankings volatile.
          </p>
        </>
      }
    >
      {leader && (
        <LeaderCard
          badge="#1 · Projected MVP"
          player={leader.player}
          playerId={leader.playerId}
          award="mvp"
          team={leader.team}
          insight={leader.insight}
          seasonLine={seasonLine(leader)}
          stats={[
            { label: "Projected Vote Share", value: pct(leader.model2Share) },
            { label: "Dominance Score", value: one(leader.mvpIndex) },
            { label: "Points per game", value: one(leader.pts) },
            { label: "Rebounds per game", value: one(leader.reb) },
            { label: "True Shooting", value: pct(leader.tsPct) },
            { label: "Model 1 Rank", value: rank(leader.model1Rank) },
          ]}
        />
      )}
      {day && day.players.length > 1 && (
        <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_21rem] xl:items-start">
          <RaceTable<Prediction>
            title="The rest of the top 10"
            award="mvp"
            rows={day.players.slice(1)}
            rowKey={(p) => p.playerId}
            rank={(p) => p.model2Rank}
            player={(p) => p.player}
            team={(p) => p.team}
            insight={(p) => p.insight}
            seasonLine={seasonLine}
            columns={[
              { header: "Vote Share", width: "5.6rem", cell: (p) => pct(p.model2Share), tone: "primary" },
              { header: "Dominance", width: "5.6rem", cell: (p) => one(p.mvpIndex), tone: "primary" },
              { header: "PTS", cell: (p) => one(p.pts) },
              { header: "TS%", cell: (p) => pct(p.tsPct) },
              { header: "BPM", cell: (p) => signed(p.bpm) },
              { header: "VORP", cell: (p) => one(p.vorp), tone: "muted", wideOnly: true },
              { header: "Model 1", cell: (p) => rank(p.model1Rank), comparison: true },
            ]}
            mobileDetails={(p) => [`${one(p.pts)} PTS`, `${pct(p.tsPct)} TS`, `Model 1 ${rank(p.model1Rank)}`]}
            mobilePrimary={(p) => pct(p.model2Share)}
            mobileSecondary={(p) => `Dom ${one(p.mvpIndex)}`}
          />
          <LadderPanel ladder={ladder} />
        </div>
      )}
    </RacePage>
  );
}
