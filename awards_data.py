"""
Awards data layer: historical voting for every major NBA award, full advanced stats, stable player
IDs and rookie flags, built from Basketball-Reference (bbref) pages cached as raw HTML.

Why raw HTML: bbref player cells carry a unique player ID (data-append-csv="jokicni01") that
pandas.read_html throws away, and several award tables (DPOY, 6MOY, MIP, Clutch) sit inside HTML
comments that read_html never sees. Caching the raw page means any future parsing change (a new
award, a new column) needs no re-download.

Outputs (data/processed/awards/):
  award_votes.parquet           one row per season x award x vote-getter (MVP, ROY, DPOY, 6MOY, MIP, Clutch)
  advanced_full.parquet         one row per player-season: every bbref advanced column, per-game box
                                score (pts_per_g, mp_per_g, ...), bbref_id, is_rookie, nba_player_id
  rookies.parquet               bbref's official rookie list per season, cross-checked with NBA.com (1997+)
  player_crosswalk.parquet      bbref_id <-> nba_api PLAYER_ID (players with 1996-97+ seasons)
  drafts.parquet                every draft 1976+: bbref_id, draft year, overall pick
  team_ratings.parquet          team-season offense/defense/net ratings (raw, league-relative, rank)

advanced_full also carries the context columns the award models need:
  ROY    draft_year, draft_pick, undrafted
  DPOY   team_win_pct, team_drtg (+ league-relative, rank), top5_team_defense, is_center
  all    prev_<award>_share: the player's vote share for each award the previous season
         (reputation; known before the season starts, so not a leak)
  2014+  darko_dpm / darko_odpm / darko_ddpm: DARKO's overall, offensive and defensive DPM
         (data/raw/darko_<season>.csv, matched by accent-folded name plus the alias map in
         rebuild_model2.py; DARKO's historical files have no player IDs)
Traded players get their last team's ratings.

Usage:
    python awards_data.py                    # build everything (fetches only pages not cached yet)
    python awards_data.py --start 2020 --end 2024
    python awards_data.py --refresh          # re-download every page
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup, Comment
from nba_api.stats.endpoints import leaguedashplayerstats

import data_pipeline as dp

BBREF = "https://www.basketball-reference.com"
PAGES = {
    "awards": BBREF + "/awards/awards_{season}.html",
    "advanced": BBREF + "/leagues/NBA_{season}_advanced.html",
    "per_game": BBREF + "/leagues/NBA_{season}_per_game.html",
    "rookies": BBREF + "/leagues/NBA_{season}_rookies.html",
    "draft": BBREF + "/draft/NBA_{season}.html",            # {season} = draft year
    "ratings": BBREF + "/leagues/NBA_{season}_ratings.html",
    "league": BBREF + "/leagues/NBA_{season}.html",          # fallback team ratings (see parse_ratings)
}
DARKO_FIRST_SEASON = 2014
FIRST_DRAFT = 1976  # Larry Bird (1979-80 rookie) was drafted in 1978; 1976 covers every 1980+ rookie
HTML_DIR = dp.RAW_DIR / "html" / "bbref"
OUT_DIR = dp.PROC_DIR / "awards"

# bbref table id -> award code. Coach of the Year ("coy") is skipped: it's not a player award.
AWARD_TABLES = {"mvp": "MVP", "roy": "ROY", "dpoy": "DPOY", "smoy": "6MOY", "mip": "MIP", "clutch_poy": "CLUTCH"}
TOTAL_TEAM = re.compile(r"\dTM|TOT")
# Letters that Unicode accent-folding can't reduce to ASCII (dp.normalize_name would drop them)
TRANSLIT = str.maketrans({"ı": "i", "İ": "I", "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
                          "ß": "ss", "æ": "ae", "Æ": "AE"})


def name_key(name: str) -> str:
    return dp.normalize_name(str(name).translate(TRANSLIT))


# --------------------------------------------------------------------------- raw HTML cache
def fetch_html(kind: str, season: int, refresh: bool = False) -> str | None:
    """Cached bbref page as text, or None if bbref has no such page (404, remembered in a marker)."""
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    path = HTML_DIR / f"{kind}_{season}.html"
    missing = path.with_suffix(".404")
    if not refresh:
        if path.exists():
            return path.read_text(encoding="utf-8")
        if missing.exists():
            return None

    url = PAGES[kind].format(season=season)

    def get():
        r = requests.get(url, headers=dp.HEADERS, timeout=30)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 60)))
            raise RuntimeError("429 rate limited")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content.decode("utf-8")

    html = dp._retry(get, f"GET {url}")
    time.sleep(dp.BBREF_SLEEP)  # only after real network requests
    if html is None:
        missing.touch()
        return None
    path.write_text(html, encoding="utf-8")
    missing.unlink(missing_ok=True)
    return html


# --------------------------------------------------------------------------- HTML parsing
def all_tables(html: str) -> dict[str, BeautifulSoup]:
    """Every <table> by id, including those bbref hides inside HTML comments."""
    soup = BeautifulSoup(html, "lxml")
    tables = {t.get("id"): t for t in soup.find_all("table") if t.get("id")}
    for c in soup.find_all(string=lambda s: isinstance(s, Comment) and "<table" in s):
        for t in BeautifulSoup(c, "lxml").find_all("table"):
            if t.get("id") and t.get("id") not in tables:
                tables[t.get("id")] = t
    return tables


PLAYER_HREF = re.compile(r"/players/[a-z]/([a-z0-9]+)\.html")
TEAM_HREF = re.compile(r"/teams/([A-Z0-9]{3})/\d{4}\.html")


def table_rows(table, key: str = "bbref_id") -> list[dict]:
    """Body rows as {data-stat: text}. Player cells also yield 'bbref_id' (from data-append-csv or the
    player link) and team cells 'team_abbr' (from the team-season link). Rows without `key` and
    repeated header rows are skipped."""
    out = []
    for tr in table.find("tbody").find_all("tr"):
        if "thead" in (tr.get("class") or []):
            continue
        row = {}
        for cell in tr.find_all(["th", "td"]):
            stat = cell.get("data-stat")
            if not stat:
                continue
            row[stat] = cell.get_text(strip=True)
            if cell.get("data-append-csv"):
                row["bbref_id"] = cell["data-append-csv"]
            link = cell.find("a")
            if link and link.get("href"):
                if (m := PLAYER_HREF.search(link["href"])) and "bbref_id" not in row:
                    row["bbref_id"] = m.group(1)
                elif m := TEAM_HREF.search(link["href"]):
                    row["team_abbr"] = m.group(1)
        if row.get(key):
            out.append(row)
    return out


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace("%", "", regex=False).replace({"": None}), errors="coerce")


def parse_award_votes(season: int, html: str) -> pd.DataFrame:
    tables = all_tables(html)
    frames = []
    for table_id, award in AWARD_TABLES.items():
        if table_id not in tables:
            continue
        df = pd.DataFrame(table_rows(tables[table_id]))
        if df.empty:
            continue
        rank_txt = df.get("rank", pd.Series([""] * len(df))).astype(str)
        frames.append(pd.DataFrame({
            "season_id": season,
            "award": award,
            "bbref_id": df["bbref_id"],
            "player": df["player"],
            "age": _num(df.get("age", pd.Series(dtype=str))),
            "team": df.get("team_id", df.get("team_name_abbr")),
            "rank": _num(rank_txt.str.replace("T", "", regex=False)),
            "rank_tied": rank_txt.str.endswith("T"),
            "first_place_votes": _num(df.get("votes_first", pd.Series(dtype=str))),
            "points_won": _num(df["points_won"]),
            "points_max": _num(df["points_max"]),
            "share": _num(df["award_share"]),
        }))
    if not frames:
        return pd.DataFrame()
    votes = pd.concat(frames, ignore_index=True)
    # Winner = top share (handles co-winners, e.g. ROY 1995 and 2000)
    votes["is_winner"] = votes["share"] == votes.groupby("award")["share"].transform("max")
    return votes


def _one_row_per_player(df: pd.DataFrame, season: int) -> pd.DataFrame:
    """Season tables list traded players once per team plus a combined (TOT / 2TM) row. Keep the
    combined row, set its team to the last stint, record the number of teams, convert stats to numbers."""
    df = df.rename(columns={"name_display": "player", "team_name_abbr": "team", "team_id": "team"})
    df = df.drop(columns=[c for c in ("ranker", "awards", "team_abbr") if c in df.columns])
    df["season_id"] = season

    is_total = df["team"].astype(str).str.fullmatch(TOTAL_TEAM.pattern)
    stints = df[~is_total]
    last_team = stints.groupby("bbref_id")["team"].last()
    n_teams = stints.groupby("bbref_id")["team"].nunique()
    multi = df["bbref_id"].map(df["bbref_id"].value_counts()) > 1
    df = df[~multi | is_total].copy()
    df["n_teams"] = df["bbref_id"].map(n_teams).fillna(1).astype(int)
    df["team"] = df["bbref_id"].map(last_team).fillna(df["team"])

    for col in df.columns.difference(["bbref_id", "player", "team", "pos", "season_id", "n_teams"]):
        df[col] = _num(df[col])
    return df.reset_index(drop=True)


def parse_advanced(season: int, html: str) -> pd.DataFrame:
    """One row per player-season of bbref's advanced table (traded players: combined row, last team)."""
    return _one_row_per_player(pd.DataFrame(table_rows(all_tables(html)["advanced"])), season)


PER_GAME_COLS = ["pts_per_g", "mp_per_g", "trb_per_g", "ast_per_g", "stl_per_g", "blk_per_g", "tov_per_g",
                 "fg_pct", "fg3_pct", "ft_pct", "efg_pct"]


def parse_per_game(season: int, html: str) -> pd.DataFrame:
    """Per-game box score (points, minutes, ...) for each player-season, keyed by bbref_id."""
    df = _one_row_per_player(pd.DataFrame(table_rows(all_tables(html)["per_game_stats"])), season)
    return df[["season_id", "bbref_id"] + [c for c in PER_GAME_COLS if c in df.columns]]


def parse_rookies(season: int, html: str) -> pd.DataFrame:
    rows = table_rows(all_tables(html)["rookies"])
    df = pd.DataFrame(rows)[["bbref_id", "player"]].drop_duplicates("bbref_id")
    df["season_id"] = season
    return df


def parse_draft(draft_year: int, html: str) -> pd.DataFrame:
    df = pd.DataFrame(table_rows(all_tables(html)["stats"]))
    return pd.DataFrame({
        "bbref_id": df["bbref_id"],
        "player": df["player"],
        "draft_year": draft_year,
        "draft_pick": _num(df["pick_overall"]),
        "draft_team": df["team_id"],
    })


def parse_ratings(season: int, html: str) -> pd.DataFrame:
    df = pd.DataFrame(table_rows(all_tables(html)["ratings"], key="team_abbr"))
    out = pd.DataFrame({
        "season_id": season,
        "team": df["team_abbr"],
        "team_name": df["team_name"],
        "team_wins": _num(df["wins"]),
        "team_losses": _num(df["losses"]),
        "team_win_pct": _num(df["win_loss_pct"]),
        "team_ortg": _num(df["off_rtg"]),
        "team_drtg": _num(df["def_rtg"]),
        "team_nrtg": _num(df["net_rtg"]),
    })
    return out


def fill_ratings_from_league(ratings: pd.DataFrame, html: str) -> pd.DataFrame:
    """The ratings page leaves ORtg/DRtg blank for 1980-83; the league page's team advanced table has them."""
    adv = pd.DataFrame(table_rows(all_tables(html)["advanced-team"], key="team_abbr"))
    adv = adv.set_index("team_abbr")
    out = ratings.copy()
    for col, src in (("team_ortg", "off_rtg"), ("team_drtg", "def_rtg"), ("team_nrtg", "net_rtg")):
        out[col] = out[col].fillna(out["team"].map(_num(adv[src])))
    return out


def add_relative_ratings(out: pd.DataFrame) -> pd.DataFrame:
    # League-relative: defense is "points allowed per 100", so lower is better; negative = better than average
    out["team_drtg_rel"] = out["team_drtg"] - out["team_drtg"].mean()
    out["team_drtg_rank"] = out["team_drtg"].rank(method="min").astype("Int64")  # 1 = best defense; <NA> if unrated
    return out


# --------------------------------------------------------------------------- NBA.com cross-references
def nba_rookie_ids(season: int, refresh: bool = False) -> set[str]:
    """NBA.com's own rookie list (1996-97+); same cache file/format as the ROY branch's fetch_rookie_ids."""
    def fetch():
        df = dp.nba_call(
            lambda: leaguedashplayerstats.LeagueDashPlayerStats(
                season=dp.season_label(season), per_mode_detailed="PerGame",
                player_experience_nullable="Rookie", timeout=dp.NBA_TIMEOUT,
            ).get_data_frames()[0],
            f"nba_api rookies {season}",
        )
        time.sleep(dp.NBA_API_SLEEP)
        return df[["PLAYER_ID", "PLAYER_NAME"]]

    return set(dp._cached(dp.RAW_DIR / f"rookies_{season}.parquet", fetch, refresh)["PLAYER_ID"].astype(str))


def add_prev_season_shares(adv: pd.DataFrame, votes: pd.DataFrame) -> pd.DataFrame:
    """prev_<award>_share: last season's vote share for every award (0 if no votes or no award yet)."""
    prev = votes.pivot_table(index=["season_id", "bbref_id"], columns="award", values="share", aggfunc="max")
    prev.columns = [f"prev_{c.lower()}_share" for c in prev.columns]
    prev = prev.reset_index().assign(season_id=lambda d: d["season_id"] + 1)
    out = adv.merge(prev, on=["season_id", "bbref_id"], how="left")
    cols = [c for c in prev.columns if c.startswith("prev_")]
    out[cols] = out[cols].fillna(0.0)
    return out


DARKO_COLUMNS = {"DPM": "darko_dpm", "ODPM": "darko_odpm", "DDPM": "darko_ddpm"}


def add_darko(adv: pd.DataFrame) -> pd.DataFrame:
    """DARKO overall/offensive/defensive DPM for seasons with a data/raw/darko_<season>.csv (2014+)."""
    from rebuild_model2 import NAME_ALIASES  # nicknames DARKO lists differently (Enes Freedom -> Kanter, ...)
    adv = adv.copy()
    for col in DARKO_COLUMNS.values():
        adv[col] = float("nan")
    for season in sorted(adv["season_id"].unique()):
        path = dp.RAW_DIR / f"darko_{season}.csv"
        if season < DARKO_FIRST_SEASON or not path.exists():
            continue
        d = pd.read_csv(path, encoding="utf-8-sig")
        d["key"] = d["Player"].map(name_key)
        d = d[~d["key"].duplicated(keep=False)].set_index("key")  # ambiguous names left unmatched
        rows = adv["season_id"] == season
        keys = adv.loc[rows, "player"].map(name_key).replace(NAME_ALIASES)
        for src, col in DARKO_COLUMNS.items():
            adv.loc[rows, col] = keys.map(pd.to_numeric(d[src], errors="coerce")).to_numpy()
    return adv


def build_crosswalk(adv: pd.DataFrame) -> pd.DataFrame:
    """bbref_id <-> nba_api PLAYER_ID, matched season by season on accent-folded name (games played
    breaks ties), then resolved per player by majority vote across seasons."""
    pairs = []
    for season in sorted(adv["season_id"].unique()):
        path = dp.RAW_DIR / f"nba_base_{season}.parquet"
        if season < dp.NBA_API_FIRST_SEASON or not path.exists():
            continue
        nba = pd.read_parquet(path)[["PLAYER_ID", "PLAYER_NAME", "GP", "AGE"]]
        nba["key"] = nba["PLAYER_NAME"].map(name_key)
        b = adv[adv["season_id"] == season][["bbref_id", "player", "games", "age"]].copy()
        b["key"] = b["player"].map(name_key)

        # Pass 1: same accent-folded name, games played within 3
        m = b.merge(nba, on="key")
        m["gdiff"] = (m["games"] - m["GP"]).abs()
        m = m.sort_values("gdiff").drop_duplicates("bbref_id").drop_duplicates("PLAYER_ID")
        m = m[m["gdiff"] <= 3]

        # Pass 2: names NBA.com shortens ("Clar. Weatherspoon", "Steven Smith"): same last name,
        # games within 1 and age within 1, accepted only when exactly one candidate fits
        b2 = b[~b["bbref_id"].isin(m["bbref_id"])].assign(last=lambda d: d["key"].str.split().str[-1])
        n2 = nba[~nba["PLAYER_ID"].isin(m["PLAYER_ID"])].assign(last=lambda d: d["key"].str.split().str[-1])
        c = b2.merge(n2, on="last", suffixes=("", "_nba"))
        c = c[((c["games"] - c["GP"]).abs() <= 1) & ((c["age"] - c["AGE"]).abs() <= 1)]
        c = c[c.groupby("bbref_id")["PLAYER_ID"].transform("size").eq(1)
              & c.groupby("PLAYER_ID")["bbref_id"].transform("size").eq(1)]

        pairs.append(pd.concat([m, c]).assign(season_id=season)[["bbref_id", "PLAYER_ID", "season_id"]])
    pairs = pd.concat(pairs, ignore_index=True)
    pairs["PLAYER_ID"] = pairs["PLAYER_ID"].astype(str)

    votes = pairs.groupby(["bbref_id", "PLAYER_ID"]).size().rename("seasons_matched").reset_index()
    votes = votes.sort_values("seasons_matched", ascending=False)
    best = votes.drop_duplicates("bbref_id")
    best = best.sort_values("seasons_matched", ascending=False).drop_duplicates("PLAYER_ID")  # one-to-one
    names = adv.sort_values("season_id").groupby("bbref_id").agg(
        player=("player", "last"), first_season=("season_id", "min"), last_season=("season_id", "max"))
    return (best.rename(columns={"PLAYER_ID": "nba_player_id"})
                .merge(names, left_on="bbref_id", right_index=True)
                .reset_index(drop=True))


# --------------------------------------------------------------------------- build
def build(start: int, end: int, refresh: bool = False):
    votes, adv, per_game, rookies, drafts, ratings = [], [], [], [], [], []
    for year in range(min(start, FIRST_DRAFT), end + 1):  # drafts start earlier than seasons
        html = fetch_html("draft", year, refresh)
        if html:
            drafts.append(parse_draft(year, html))
    for season in range(start, end + 1):
        print(f"[{season}] {dp.season_label(season)}", flush=True)
        html = fetch_html("awards", season, refresh)
        if html:
            votes.append(parse_award_votes(season, html))
        html = fetch_html("advanced", season, refresh)
        if html:
            adv.append(parse_advanced(season, html))
        html = fetch_html("per_game", season, refresh)
        if html:
            per_game.append(parse_per_game(season, html))
        html = fetch_html("rookies", season, refresh)
        if html:
            rookies.append(parse_rookies(season, html))
        html = fetch_html("ratings", season, refresh)
        if html:
            r = parse_ratings(season, html)
            if r["team_drtg"].isna().any():
                r = fill_ratings_from_league(r, fetch_html("league", season, refresh))
            ratings.append(add_relative_ratings(r))

    votes = pd.concat(votes, ignore_index=True)
    adv = pd.concat(adv, ignore_index=True)
    rookies = pd.concat(rookies, ignore_index=True)
    drafts = pd.concat(drafts, ignore_index=True)
    ratings = pd.concat(ratings, ignore_index=True)

    # Per-game box score, and the season's schedule length (lockouts/bubble: 50, 66, 72 ... 82 games)
    adv = adv.merge(pd.concat(per_game, ignore_index=True), on=["season_id", "bbref_id"], how="left")
    season_games = (ratings["team_wins"] + ratings["team_losses"]).groupby(ratings["season_id"]).max()
    adv["season_games"] = adv["season_id"].map(season_games)

    # Draft context: a player's most recent draft (a few re-entered the draft)
    last_draft = drafts.sort_values("draft_year").drop_duplicates("bbref_id", keep="last")
    adv = adv.merge(last_draft[["bbref_id", "draft_year", "draft_pick"]], on="bbref_id", how="left")
    adv["undrafted"] = adv["draft_pick"].isna()
    # Team context (traded players: their last team)
    adv = adv.merge(ratings.drop(columns=["team_name"]), on=["season_id", "team"], how="left")
    adv["top5_team_defense"] = adv["team_drtg_rank"] <= 5
    adv["is_center"] = adv["pos"] == "C"
    # Reputation and DARKO defense
    adv = add_prev_season_shares(adv, votes)
    adv = add_darko(adv)

    xwalk = build_crosswalk(adv)
    to_nba = xwalk.set_index("bbref_id")["nba_player_id"]
    adv["nba_player_id"] = adv["bbref_id"].map(to_nba)
    votes["nba_player_id"] = votes["bbref_id"].map(to_nba)

    rookie_keys = set(zip(rookies["season_id"], rookies["bbref_id"]))
    adv["is_rookie"] = [(s, b) in rookie_keys for s, b in zip(adv["season_id"], adv["bbref_id"])]

    rookies["nba_player_id"] = rookies["bbref_id"].map(to_nba)
    nba_lists = {s: nba_rookie_ids(s) for s in range(max(start, dp.NBA_API_FIRST_SEASON), end + 1)}
    rookies["in_nba_rookie_list"] = [
        (pid in nba_lists[s]) if s in nba_lists and pd.notna(pid) else pd.NA
        for s, pid in zip(rookies["season_id"], rookies["nba_player_id"])
    ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    votes.to_parquet(OUT_DIR / "award_votes.parquet", index=False)
    adv.to_parquet(OUT_DIR / "advanced_full.parquet", index=False)
    rookies.to_parquet(OUT_DIR / "rookies.parquet", index=False)
    xwalk.to_parquet(OUT_DIR / "player_crosswalk.parquet", index=False)
    drafts.to_parquet(OUT_DIR / "drafts.parquet", index=False)
    ratings.to_parquet(OUT_DIR / "team_ratings.parquet", index=False)
    return votes, adv, rookies, xwalk, nba_lists


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=int, default=1980)
    ap.add_argument("--end", type=int, default=2026)
    ap.add_argument("--refresh", action="store_true", help="re-download pages even if cached")
    a = ap.parse_args()
    votes, adv, rookies, xwalk, _ = build(a.start, a.end, a.refresh)
    print(f"\naward_votes: {len(votes)} rows | advanced_full: {len(adv)} player-seasons | "
          f"rookies: {len(rookies)} | crosswalk: {len(xwalk)} players -> {OUT_DIR}")


if __name__ == "__main__":
    main()
