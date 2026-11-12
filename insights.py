"""
Player insights for the award dashboards.

  fetch_recent_games   last N games' box scores from a player's Basketball-Reference game log
  summarize            rule-based one-sentence summary from rank movement, recent games and season stats
  fetch_mvp_ladder     the latest official NBA.com "Kia MVP Ladder" Top 10 (author, date, link)

Usage (prints today's insights without touching the database):
    python insights.py --ladder
    python insights.py --games wembavi01
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

import awards_data as ad
import data_pipeline as dp

GAMELOG_URL = ad.BBREF + "/players/{initial}/{bbref_id}/gamelog/{season}"
GAMELOG_DIR = dp.RAW_DIR / "html" / "bbref" / "gamelogs"

NBA_HEADERS = {"User-Agent": "Mozilla/5.0 (personal research project; low request rate)"}
LADDER_CATEGORY_URL = "https://www.nba.com/news/category/kia-race-to-the-mvp-ladder"
NBA_SLEEP = 3.0
LADDER_ENTRY = re.compile(r"^(\d{1,2})\.\s+(.+?),\s+(.+)$")  # "1. Luka Dončić, Los Angeles Lakers"


# --------------------------------------------------------------------------- recent games (bbref)
def _gamelog_html(bbref_id: str, season: int, refresh: bool) -> str:
    """Cached per player per day: a re-run the same day makes no new request."""
    path = GAMELOG_DIR / str(season) / f"{bbref_id}_{date.today().isoformat()}.html"
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")
    url = GAMELOG_URL.format(initial=bbref_id[0], bbref_id=bbref_id, season=season)

    def get():
        r = requests.get(url, headers=dp.HEADERS, timeout=30)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 60)))
            raise RuntimeError("429 rate limited")
        r.raise_for_status()
        return r.content.decode("utf-8")

    html = dp._retry(get, f"GET {url}")
    time.sleep(dp.BBREF_SLEEP)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return html


def _num(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def fetch_recent_games(bbref_id: str, season: int, n: int = 3, refresh: bool = False) -> list[dict]:
    """The player's last `n` games played (games missed are skipped), oldest first."""
    tables = ad.all_tables(_gamelog_html(bbref_id, season, refresh))
    table = tables.get("player_game_log_reg")
    if table is None:
        return []
    games = []
    for tr in table.find("tbody").find_all("tr"):
        cells = {c.get("data-stat"): c.get_text(strip=True) for c in tr.find_all(["th", "td"]) if c.get("data-stat")}
        if not cells.get("pts") or not cells.get("date"):
            continue  # did not play / inactive / header row
        games.append({
            "date": cells["date"],
            "opp": cells.get("opp_name_abbr"),
            "home": cells.get("game_location") != "@",
            "result": cells.get("game_result"),
            "pts": _num(cells.get("pts")), "reb": _num(cells.get("trb")), "ast": _num(cells.get("ast")),
            "stl": _num(cells.get("stl")), "blk": _num(cells.get("blk")), "fg_pct": _num(cells.get("fg_pct")),
        })
    return games[-n:]


# --------------------------------------------------------------------------- summaries (rule based)
def _movement(rank: int | None, prev: int | None, had_prior_day: bool) -> str:
    if rank is None:
        return ""
    if not had_prior_day:
        return f"Sits at #{rank}"
    if prev is None:
        return f"Enters the race at #{rank}"
    if rank == 1:
        return "Holds the #1 spot" if prev == 1 else f"Takes over the #1 spot from #{prev}"
    diff = prev - rank
    if diff > 0:
        return f"Climbs {diff} spot{'s' if diff > 1 else ''} to #{rank}"
    if diff < 0:
        return f"Slips {-diff} spot{'s' if diff < -1 else ''} to #{rank}"
    return f"Holds steady at #{rank}"


def _count_word(n: int) -> str:
    return {2: "two", 3: "three"}.get(n, str(n))


def _scoring_reason(games: list[dict], season_pts: float | None) -> str | None:
    pts = [g["pts"] for g in games if g["pts"] is not None]
    if not pts:
        return None
    streak = 0
    for p in reversed(pts):  # consecutive 30-point games ending with the latest
        if p < 30:
            break
        streak += 1
    if streak == 3:
        return "three straight 30-point games"
    if streak == 2:
        return "back-to-back 30-point games"
    if max(pts) >= 40:
        return f"a {int(max(pts))}-point outburst in the last three games"
    avg = sum(pts) / len(pts)
    if season_pts is not None and avg >= season_pts + 5:
        return f"{avg:.1f} points per game over the last three, up from {season_pts:.1f}"
    dd = sum(1 for g in games if sum(1 for k in ("pts", "reb", "ast") if (g[k] or 0) >= 10) >= 2)
    if dd >= 2:
        return ("double-doubles in each of the last three games" if dd == len(games) == 3
                else f"double-doubles in {_count_word(dd)} of the last {_count_word(len(games))} games")
    if season_pts is not None and avg <= season_pts - 5:
        return f"despite a cooler stretch ({avg:.1f} points per game over the last three)"
    return None


def _defense_reason(games: list[dict], team_drtg_rank: int | None) -> str | None:
    blk = sum(g["blk"] or 0 for g in games)
    stl = sum(g["stl"] or 0 for g in games)
    if games and blk >= 3 * len(games):
        return f"{int(blk)} blocks over the last {_count_word(len(games))} games"
    if games and stl >= 2 * len(games):
        return f"{int(stl)} steals over the last {_count_word(len(games))} games"
    if team_drtg_rank == 1:
        return "anchoring the league's top-ranked defense"
    if team_drtg_rank is not None and team_drtg_rank <= 5:
        return f"anchoring the league's No. {team_drtg_rank} defense"
    return None


def summarize(award: str, rank: int | None, prev_rank: int | None, had_prior_day: bool,
              games: list[dict], stats: dict, group_best_ts: float | None = None) -> str:
    """1-2 sentences, e.g. 'Climbs 2 spots to #3, after back-to-back 30-point games.'

    award: "mvp" | "roy" | "dpoy". stats: season numbers (pts, ts_pct, team_drtg_rank, ...).
    group_best_ts: the best TS% in the displayed list (lets us say "best True Shooting in the top 10").
    """
    move = _movement(rank, prev_rank, had_prior_day)
    if award == "dpoy":
        reason = _defense_reason(games, stats.get("team_drtg_rank"))
    else:
        reason = _scoring_reason(games, stats.get("pts"))
        ts = stats.get("ts_pct")
        if reason is None and ts is not None and group_best_ts is not None and ts >= group_best_ts:
            reason = f"backed by the best True Shooting in the group ({ts * 100:.1f}%)"

    # (The last game's box score isn't repeated here: the site shows the last 3 games in a table.)
    if reason and reason.startswith(("backed", "despite", "anchoring")):
        return f"{move}, {reason}."
    if reason:
        return f"{move} after {reason}."
    return f"{move}."


# --------------------------------------------------------------------------- official NBA MVP ladder
def _get_nba(url: str) -> str:
    r = requests.get(url, headers=NBA_HEADERS, timeout=30)
    r.raise_for_status()
    time.sleep(NBA_SLEEP)
    return r.text


def _next_data(html: str) -> dict:
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else {}


def latest_ladder_article() -> dict | None:
    """Newest ranked 'Kia MVP Ladder' article (skips Finals MVP ladders and the pre-season watch list)."""
    found = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("permalink") and o.get("title") and o.get("date"):
                found.append({"title": o["title"], "url": o["permalink"], "date": o["date"]})
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(_next_data(_get_nba(LADDER_CATEGORY_URL)))
    ranked = [a for a in found
              if a["title"].lower().startswith("kia mvp ladder")
              and "watch" not in a["url"].lower() and "finals" not in a["url"].lower()]
    return max(ranked, key=lambda a: a["date"]) if ranked else None


def fetch_mvp_ladder() -> dict | None:
    """{'title', 'url', 'date', 'author', 'entries': [{'rank', 'player', 'team'}, ...]} or None."""
    article = latest_ladder_article()
    if not article:
        return None
    soup = BeautifulSoup(_get_nba(article["url"]), "lxml")
    entries = []
    for h in soup.find_all(["h2", "h3"]):
        m = LADDER_ENTRY.match(h.get_text(" ", strip=True))
        if m and 1 <= int(m.group(1)) <= 10:
            entries.append({"rank": int(m.group(1)), "player": m.group(2).strip(), "team": m.group(3).strip()})
    entries = sorted({e["rank"]: e for e in entries}.values(), key=lambda e: e["rank"])  # first heading per rank

    author = None
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            a = item.get("author") if isinstance(item, dict) else None
            if isinstance(a, dict) and a.get("name"):
                author = a["name"]
            elif isinstance(a, list) and a and isinstance(a[0], dict):
                author = a[0].get("name")
    if len(entries) < 10:
        raise ValueError(f"parsed only {len(entries)} ladder entries from {article['url']}")
    return {**article, "author": author, "entries": entries}


# --------------------------------------------------------------------------- daily orchestration
SHOWN = {"mvp": 10, "roy": 5, "dpoy": 5}  # players each page displays


def _bbref_ids_for_mvp(pool: pd.DataFrame, season: int) -> dict[str, str]:
    """NBA.com PLAYER_ID -> bbref id: the awards crosswalk first, then today's bbref advanced page by name."""
    xwalk = pd.read_parquet(ad.OUT_DIR / "player_crosswalk.parquet")
    by_nba = dict(zip(xwalk["nba_player_id"].astype(str), xwalk["bbref_id"]))
    live = ad.parse_advanced(season, ad.fetch_html("advanced", season, refresh=False))
    by_name = dict(zip(live["player"].map(ad.name_key), live["bbref_id"]))
    out = {}
    for pid, name in zip(pool["PLAYER_ID"].astype(str), pool["PLAYER"]):
        out[pid] = by_nba.get(pid) or by_name.get(ad.name_key(name))
    return out


def build_and_save(engine, season: int, mvp_pool: pd.DataFrame, awards: dict | None,
                   prediction_date: date | None = None, refresh: bool = False) -> list[str]:
    """Recent games + summaries for every player shown on the site, and the latest NBA.com ladder.
    Returns printable lines. Each award (and the ladder) is isolated: one failing doesn't stop the rest."""
    from db_sync import previous_ranks, write_insights, write_mvp_ladder

    day = prediction_date or date.today()
    lines, errors = [], []
    races = {"mvp": (mvp_pool.sort_values("M2_RANK").head(SHOWN["mvp"]), "model2_rank")}
    if awards:
        races["roy"] = (awards["roy"].sort_values("m1_rank").head(SHOWN["roy"]), "model1_rank")
        races["dpoy"] = (awards["dpoy"].sort_values("m1_rank").head(SHOWN["dpoy"]), "model1_rank")

    for award, (top, rank_col) in races.items():
        try:
            had_prior, prev = previous_ranks(engine, award, rank_col, season, day)
            if award == "mvp":
                ids = _bbref_ids_for_mvp(top, season)
                rows = [dict(player_id=str(r.PLAYER_ID), bbref_id=ids.get(str(r.PLAYER_ID)), player=r.PLAYER,
                             rank=int(r.M2_RANK), stats={"pts": r.PTS, "ts_pct": r.TS_PCT}) for r in top.itertuples()]
                best_ts = float(top["TS_PCT"].max())
            else:
                rows = [dict(player_id=r.bbref_id, bbref_id=r.bbref_id, player=r.player, rank=int(r.m1_rank),
                             stats={"pts": r.pts_per_g, "ts_pct": r.ts_pct,
                                    "team_drtg_rank": None if pd.isna(r.team_drtg_rank) else int(r.team_drtg_rank)})
                        for r in top.itertuples()]
                best_ts = float(top["ts_pct"].max())

            out = []
            for row in rows:
                games = fetch_recent_games(row["bbref_id"], season, refresh=refresh) if row["bbref_id"] else []
                prev_rank = prev.get(row["player_id"])
                summary = summarize(award, row["rank"], prev_rank, had_prior, games, row["stats"], best_ts)
                out.append({"player_id": row["player_id"], "summary": summary, "recent_games": games,
                            "rank_change": (prev_rank - row["rank"]) if prev_rank is not None else None})
                lines.append(f"  {award.upper():4s} #{row['rank']:<2d} {row['player']}: {summary}")
            write_insights(engine, award, out, season, day)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{award} insights: {type(e).__name__}: {e}")

    try:
        ladder = fetch_mvp_ladder()
        if ladder:
            ours = dict(zip(mvp_pool["PLAYER"].map(ad.name_key), mvp_pool["PLAYER_ID"].astype(str)))
            ids = {e["rank"]: ours.get(ad.name_key(e["player"])) for e in ladder["entries"]}
            n = write_mvp_ladder(engine, ladder, season, ids)
            lines.append(f"  NBA.com MVP Ladder: {n} entries from '{ladder['title']}' ({ladder['date'][:10]}, "
                         f"{ladder.get('author')}); {sum(v is not None for v in ids.values())} matched to our MVP race")
    except Exception as e:  # noqa: BLE001
        errors.append(f"MVP ladder: {type(e).__name__}: {e}")

    if errors:
        raise RuntimeError("; ".join(errors) + " (other insights were saved)")
    return lines


# --------------------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ladder", action="store_true", help="print the latest official NBA MVP ladder")
    ap.add_argument("--games", metavar="BBREF_ID", help="print a player's last 3 games")
    ap.add_argument("--season", type=int, default=2027)
    a = ap.parse_args()
    if a.ladder:
        lad = fetch_mvp_ladder()
        print(f"{lad['title']} - {lad['author']} ({lad['date'][:10]})\n{lad['url']}")
        print(pd.DataFrame(lad["entries"]).to_string(index=False))
    if a.games:
        print(pd.DataFrame(fetch_recent_games(a.games, a.season)).to_string(index=False))


if __name__ == "__main__":
    main()
