// Team lookup shared by every page. The MVP pipeline stores NBA.com abbreviations (BKN, CHA, PHX);
// the ROY and DPOY pipelines store Basketball-Reference ones (BRK, CHO, PHO). Both resolve to the
// same team, and the site always displays the NBA.com code.

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

/** Basketball-Reference code -> NBA.com code (only where they differ for current franchises). */
const BBREF_TO_NBA: Record<string, string> = { BRK: "BKN", CHO: "CHA", PHO: "PHX" };

/** Normalized NBA.com abbreviation for display ("BRK" -> "BKN"); unknown codes pass through. */
export function teamCode(abbr: string | null | undefined): string | null {
  if (!abbr) return null;
  const code = abbr.toUpperCase();
  return BBREF_TO_NBA[code] ?? code;
}

/** Full team name for either source's abbreviation ("CHO" and "CHA" -> "Charlotte Hornets"). */
export function teamName(abbr: string | null | undefined): string {
  const code = teamCode(abbr);
  return code ? (TEAM_NAMES[code] ?? code) : "";
}
