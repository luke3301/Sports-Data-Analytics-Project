// Team lookup shared by every page. The MVP pipeline stores NBA.com abbreviations (BKN, CHA, PHX);
// the ROY and DPOY pipelines store Basketball-Reference ones (BRK, CHO, PHO); the NBA.com ladder uses
// full names. All resolve to one team, and the site always displays the NBA.com code.
// Team ids come from nba_api's static team table. Logos are the official NBA.com SVGs, downloaded once
// into public/logos/<CODE>.svg and served from this site: NBA.com's CDN stalls requests from many
// browsers (bot protection), so hot-linking it would leave logos blank and keep pages loading.

type Team = { name: string; id: number };

const TEAMS: Record<string, Team> = {
  ATL: { name: "Atlanta Hawks", id: 1610612737 }, BOS: { name: "Boston Celtics", id: 1610612738 },
  BKN: { name: "Brooklyn Nets", id: 1610612751 }, CHA: { name: "Charlotte Hornets", id: 1610612766 },
  CHI: { name: "Chicago Bulls", id: 1610612741 }, CLE: { name: "Cleveland Cavaliers", id: 1610612739 },
  DAL: { name: "Dallas Mavericks", id: 1610612742 }, DEN: { name: "Denver Nuggets", id: 1610612743 },
  DET: { name: "Detroit Pistons", id: 1610612765 }, GSW: { name: "Golden State Warriors", id: 1610612744 },
  HOU: { name: "Houston Rockets", id: 1610612745 }, IND: { name: "Indiana Pacers", id: 1610612754 },
  LAC: { name: "LA Clippers", id: 1610612746 }, LAL: { name: "Los Angeles Lakers", id: 1610612747 },
  MEM: { name: "Memphis Grizzlies", id: 1610612763 }, MIA: { name: "Miami Heat", id: 1610612748 },
  MIL: { name: "Milwaukee Bucks", id: 1610612749 }, MIN: { name: "Minnesota Timberwolves", id: 1610612750 },
  NOP: { name: "New Orleans Pelicans", id: 1610612740 }, NYK: { name: "New York Knicks", id: 1610612752 },
  OKC: { name: "Oklahoma City Thunder", id: 1610612760 }, ORL: { name: "Orlando Magic", id: 1610612753 },
  PHI: { name: "Philadelphia 76ers", id: 1610612755 }, PHX: { name: "Phoenix Suns", id: 1610612756 },
  POR: { name: "Portland Trail Blazers", id: 1610612757 }, SAC: { name: "Sacramento Kings", id: 1610612758 },
  SAS: { name: "San Antonio Spurs", id: 1610612759 }, TOR: { name: "Toronto Raptors", id: 1610612761 },
  UTA: { name: "Utah Jazz", id: 1610612762 }, WAS: { name: "Washington Wizards", id: 1610612764 },
};

/** Basketball-Reference code -> NBA.com code (only where they differ for current franchises). */
const BBREF_TO_NBA: Record<string, string> = { BRK: "BKN", CHO: "CHA", PHO: "PHX" };

/** Full-name lookup (NBA.com ladder), including the Clippers' longer form. */
const BY_NAME: Record<string, string> = Object.fromEntries([
  ...Object.entries(TEAMS).map(([code, t]) => [t.name.toLowerCase(), code]),
  ["los angeles clippers", "LAC"],
]);

/** Normalized NBA.com abbreviation for display ("BRK" -> "BKN"); unknown codes pass through. */
export function teamCode(abbr: string | null | undefined): string | null {
  if (!abbr) return null;
  const code = abbr.toUpperCase();
  return BBREF_TO_NBA[code] ?? code;
}

/** Full team name for either source's abbreviation ("CHO" and "CHA" -> "Charlotte Hornets"). */
export function teamName(abbr: string | null | undefined): string {
  const code = teamCode(abbr);
  return code ? (TEAMS[code]?.name ?? code) : "";
}

/** NBA.com code for a full team name ("Los Angeles Lakers" -> "LAL"), or null. */
export function teamCodeFromName(name: string | null | undefined): string | null {
  return name ? (BY_NAME[name.trim().toLowerCase()] ?? null) : null;
}

/** Team logo path (self-hosted SVG) for either source's abbreviation, or null for unknown teams. */
export function teamLogo(abbr: string | null | undefined): string | null {
  const code = teamCode(abbr);
  return code && TEAMS[code] ? `/logos/${code}.svg` : null;
}
