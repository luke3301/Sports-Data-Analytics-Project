// One source of truth for stat definitions: used by the table-header tooltips and the footer glossary,
// so the two can never disagree. Keys match column headers exactly.

export const GLOSSARY: Record<string, { term: string; definition: string }> = {
  "TS%": {
    term: "True Shooting % (TS%)",
    definition: "Scoring efficiency that counts 2s, 3s and free throws together: points ÷ (2 × (FGA + 0.44 × FTA)). League average is around 58%.",
  },
  BPM: {
    term: "Box Plus/Minus (BPM)",
    definition: "Points per 100 possessions a player adds over a league-average player, estimated from the box score. Roughly +4 is All-Star level, +6 All-NBA and +8 MVP level.",
  },
  DBPM: {
    term: "Defensive Box Plus/Minus (DBPM)",
    definition: "The defensive part of BPM: points per 100 possessions saved versus an average defender, estimated from steals, blocks, rebounds and team defense.",
  },
  VORP: {
    term: "Value Over Replacement Player (VORP)",
    definition: "Total value added over a freely available replacement-level player, based on BPM and minutes played. It accumulates over the season.",
  },
  DWS: {
    term: "Defensive Win Shares (DWS)",
    definition: "Estimated wins contributed by a player's defense, built from team defensive rating and individual defensive stats. It accumulates over the season.",
  },
  "Vote Share": {
    term: "Vote Share",
    definition: "The model's predicted fraction of award voting points (100% = every first-place vote).",
  },
  Dominance: {
    term: "Dominance Score",
    definition: "Our unbounded measure of statistical dominance: 35 is a typical rotation player, 82 an average MVP season, 90+ historic.",
  },
  Score: {
    term: "Score",
    definition: "The voter model's 0-100 index: 100 matches the strongest award case in the training history.",
  },
};

/** Terms shown in the footer glossary, in reading order. */
export const GLOSSARY_ORDER = ["Vote Share", "Dominance", "Score", "TS%", "BPM", "DBPM", "VORP", "DWS"];
