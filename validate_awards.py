"""
Validate the awards data layer built by awards_data.py. Exits with status 1 if any hard check fails.

Usage:  python validate_awards.py
"""
from __future__ import annotations

import sys

import pandas as pd

import data_pipeline as dp
from awards_data import OUT_DIR

# First season with a VOTING table on bbref. Sixth Man began in 1982-83, but bbref only lists the
# 1983 winner (no voting), so its voting data starts in 1984.
FIRST_SEASON = {"MVP": 1980, "ROY": 1980, "DPOY": 1983, "6MOY": 1984, "MIP": 1986, "CLUTCH": 2023}
CO_WINNERS = {("ROY", 1995), ("ROY", 2000)}  # Hill/Kidd and Brand/Francis shared Rookie of the Year

# Independent spot checks: (award, season) -> bbref_id(s) of the winner(s)
KNOWN_WINNERS = {
    ("ROY", 1980): {"birdla01"}, ("ROY", 1985): {"jordami01"}, ("ROY", 1990): {"robinda01"},
    ("ROY", 1993): {"onealsh01"}, ("ROY", 1995): {"hillgr01", "kiddja01"}, ("ROY", 1998): {"duncati01"},
    ("ROY", 2000): {"brandel01", "francst01"}, ("ROY", 2004): {"jamesle01"}, ("ROY", 2008): {"duranke01"},
    ("ROY", 2009): {"rosede01"}, ("ROY", 2011): {"griffbl01"}, ("ROY", 2024): {"wembavi01"},
    ("DPOY", 1983): {"moncrsi01"}, ("DPOY", 1993): {"olajuha01"}, ("DPOY", 1994): {"olajuha01"},
    ("DPOY", 1995): {"mutomdi01"}, ("DPOY", 2002): {"wallabe01"}, ("DPOY", 2003): {"wallabe01"},
    ("DPOY", 2009): {"howardw01"}, ("DPOY", 2010): {"howardw01"}, ("DPOY", 2011): {"howardw01"},
    ("DPOY", 2015): {"leonaka01"}, ("DPOY", 2016): {"leonaka01"}, ("DPOY", 2018): {"goberru01"},
    ("DPOY", 2019): {"goberru01"}, ("DPOY", 2020): {"antetgi01"}, ("DPOY", 2021): {"goberru01"},
    ("DPOY", 2024): {"goberru01"},
    ("MVP", 1988): {"jordami01"}, ("MVP", 2000): {"onealsh01"}, ("MVP", 2016): {"curryst01"},
    ("MVP", 2023): {"embiijo01"}, ("MVP", 2024): {"jokicni01"},
}
DEFENSIVE = ["dws", "dbpm", "stl_pct", "blk_pct", "drb_pct"]
# Draft spot checks: bbref_id -> overall pick (None = undrafted)
KNOWN_PICKS = {"birdla01": 6, "duncati01": 1, "jamesle01": 1, "jokicni01": 41, "brogdma01": 36,
               "wembavi01": 1, "wallabe01": None}
# Teams per season (expansion: 23 in 1981, 25 in 1989, 27 in 1990, 29 in 1996, 30 in 2005)
def expected_teams(season: int) -> int:
    return 22 if season == 1980 else 23 if season <= 1988 else 25 if season == 1989 else \
        27 if season <= 1995 else 29 if season <= 2004 else 30

failures: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def main():
    votes = pd.read_parquet(OUT_DIR / "award_votes.parquet")
    adv = pd.read_parquet(OUT_DIR / "advanced_full.parquet")
    rookies = pd.read_parquet(OUT_DIR / "rookies.parquet")
    xwalk = pd.read_parquet(OUT_DIR / "player_crosswalk.parquet")
    last = int(adv["season_id"].max())

    print("1. Award coverage (every season since the award began)")
    for award, first in FIRST_SEASON.items():
        have = set(votes.loc[votes["award"] == award, "season_id"])
        missing = sorted(set(range(first, last + 1)) - have)
        check(not missing, f"{award} {first}-{last}: {len(have)} seasons", f"missing {missing}" if missing else "")

    print("2. Exactly one winner per award-season (except known co-winners), winner is rank 1")
    w = votes[votes["is_winner"]]
    counts = w.groupby(["award", "season_id"]).size()
    extra = [k for k, n in counts.items() if n != 1 and k not in CO_WINNERS]
    check(not extra, "single winners", f"unexpected multiple winners: {extra}" if extra else "")
    check(all(counts.get(k, 0) == 2 for k in CO_WINNERS), "known co-winner seasons have 2 winners",
          ", ".join(f"{a} {s}: {', '.join(w[(w.award == a) & (w.season_id == s)].player)}" for a, s in sorted(CO_WINNERS)))
    check((w["rank"] == 1).all(), "every winner has rank 1")

    print("3. Join integrity: every vote-getter exists in that season's advanced stats")
    keys = set(zip(adv["season_id"], adv["bbref_id"]))
    orphan = votes[[(s, b) not in keys for s, b in zip(votes["season_id"], votes["bbref_id"])]]
    check(orphan.empty, f"{len(votes)} vote rows linked by bbref_id",
          f"{len(orphan)} orphans: {orphan[['season_id', 'award', 'player']].values.tolist()[:5]}" if len(orphan) else "")

    print("4. Rookie flags: every ROY vote-getter is on that season's rookie list")
    rkeys = set(zip(rookies["season_id"], rookies["bbref_id"]))
    roy = votes[votes["award"] == "ROY"]
    not_rookie = roy[[(s, b) not in rkeys for s, b in zip(roy["season_id"], roy["bbref_id"])]]
    check(not_rookie.empty, f"{len(roy)} ROY vote-getters are flagged rookies",
          f"{not_rookie[['season_id', 'player']].values.tolist()}" if len(not_rookie) else "")
    per_season = rookies.groupby("season_id").size()
    check(per_season.min() >= 30, f"rookie lists for {len(per_season)} seasons",
          f"{per_season.min()}-{per_season.max()} rookies per season")

    print("5. Rookie flags vs NBA.com's own rookie list (1997+)")
    r97 = rookies[rookies["in_nba_rookie_list"].notna()]
    agree = r97["in_nba_rookie_list"].astype(bool).mean()
    nba_total = sum(len(pd.read_parquet(dp.RAW_DIR / f"rookies_{s}.parquet")) for s in r97["season_id"].unique())
    check(agree >= 0.95, f"{agree:.1%} of {len(r97)} crosswalked bbref rookies are NBA.com rookies",
          f"bbref lists {len(rookies[rookies.season_id >= 1997])} rookies vs NBA.com {nba_total}")
    disagree = r97[~r97["in_nba_rookie_list"].astype(bool)]
    if len(disagree):
        print(f"       disagreements (sample): {disagree[['season_id', 'player']].values.tolist()[:6]}")

    print("6. MVP labels match the ones Model 1 was trained on")
    mism = []
    for s in range(1980, last + 1):
        path = dp.RAW_DIR / f"bbref_mvp_{s}.parquet"
        if not path.exists():
            continue
        old = pd.read_parquet(path).sort_values("MVP_SHARE", ascending=False).iloc[0]["NAME_KEY"]
        new = dp.normalize_name(votes[(votes.award == "MVP") & (votes.season_id == s) & votes.is_winner].player.iloc[0])
        if old != new:
            mism.append((s, old, new))
    check(not mism, "MVP winners identical to Model 1 training labels", str(mism) if mism else "")

    print("7. Spot check of known winners")
    wrong = []
    for (award, season), expected in KNOWN_WINNERS.items():
        got = set(w[(w.award == award) & (w.season_id == season)].bbref_id)
        if got != expected:
            wrong.append((award, season, sorted(expected), sorted(got)))
    check(not wrong, f"{len(KNOWN_WINNERS)} known award winners", str(wrong) if wrong else "")

    print("8. Player ID crosswalk (bbref <-> NBA.com)")
    recent = adv[(adv["season_id"] >= dp.NBA_API_FIRST_SEASON) & (adv["mp"] >= 500)]
    cov = recent["nba_player_id"].notna().mean()
    check(cov >= 0.98, f"{cov:.1%} of 1997+ player-seasons with 500+ minutes have an NBA.com ID",
          f"{len(xwalk)} players mapped")
    check(xwalk["bbref_id"].is_unique and xwalk["nba_player_id"].is_unique, "crosswalk is one-to-one")
    unmatched = recent[recent["nba_player_id"].isna()].sort_values("mp", ascending=False)
    if len(unmatched):
        print(f"       unmatched (most minutes): {unmatched[['season_id', 'player', 'mp']].head(5).values.tolist()}")

    print("9. Defensive metrics coverage")
    eligible = adv[adv["mp"] >= 500]
    for col in DEFENSIVE:
        cov = eligible[col].notna().mean()
        check(cov >= 0.99, f"{col}: {cov:.1%} of 500+ minute player-seasons")

    print("10. Draft context (ROY)")
    first = adv.drop_duplicates("bbref_id").set_index("bbref_id")
    wrong = {b: (pick, first.at[b, "draft_pick"] if b in first.index else "missing")
             for b, pick in KNOWN_PICKS.items()
             if b not in first.index or not ((pd.isna(first.at[b, "draft_pick"]) and pick is None)
                                             or first.at[b, "draft_pick"] == pick)}
    check(not wrong, f"{len(KNOWN_PICKS)} known draft picks (incl. undrafted Ben Wallace)", str(wrong) if wrong else "")
    roy_adv = roy.merge(adv[["season_id", "bbref_id", "draft_pick", "draft_year"]], on=["season_id", "bbref_id"])
    drafted = roy_adv["draft_pick"].notna().mean()
    early = roy_adv[roy_adv["draft_year"] > roy_adv["season_id"] - 1]
    check(drafted >= 0.95 and early.empty, f"{drafted:.1%} of ROY vote-getters have a draft pick; none drafted after their rookie season",
          f"undrafted: {roy_adv[roy_adv.draft_pick.isna()][['season_id', 'player']].values.tolist()}")

    print("11. Team context (DPOY)")
    ratings = pd.read_parquet(OUT_DIR / "team_ratings.parquet")
    n = ratings.groupby("season_id").size()
    bad = {s: (int(n.get(s, 0)), expected_teams(s)) for s in sorted(adv["season_id"].unique()) if n.get(s, 0) != expected_teams(s)}
    check(not bad, f"team ratings for {len(n)} seasons with the right number of teams", str(bad) if bad else "")
    cov = eligible[["team_drtg", "team_drtg_rel", "team_win_pct"]].notna().all(axis=1).mean()
    check(cov >= 0.999, f"{cov:.1%} of 500+ minute player-seasons joined to their team's ratings")
    best_d = ratings.loc[ratings.groupby("season_id")["team_drtg_rank"].idxmin()]
    print(f"       best defense, recent seasons: {best_d[best_d.season_id >= 2022][['season_id', 'team', 'team_drtg']].values.tolist()}")

    print("12. Reputation, position and DARKO features (DPOY)")
    dw = votes[(votes.award == "DPOY") & votes.is_winner].merge(adv, on=["season_id", "bbref_id"])
    repeat = dw[dw["season_id"].isin([1994, 2019, 2021])][["season_id", "player_x", "prev_dpoy_share"]]
    check((repeat["prev_dpoy_share"] > 0).all(), "repeat winners carry last season's DPOY share",
          str(repeat.round(3).values.tolist()))
    check(adv.loc[adv.season_id == 1983, "prev_dpoy_share"].eq(0).all(), "1983 (first DPOY) has no prior DPOY share")
    check(dw["is_center"].sum() >= 25, f"{int(dw['is_center'].sum())} of {len(dw)} DPOY winners are centers")
    modern = adv[(adv.season_id >= 2014) & (adv.mp >= 500)]
    cov = modern["darko_ddpm"].notna().mean()
    check(cov >= 0.97, f"DARKO DDPM for {cov:.1%} of 2014+ player-seasons with 500+ minutes")
    check(adv.loc[adv.season_id < 2014, "darko_ddpm"].isna().all(), "no DARKO values before 2014")

    print("\nAward winners by season (ROY, DPOY):")
    table = (w[w.award.isin(["ROY", "DPOY"])].groupby(["season_id", "award"])["player"]
             .agg(" & ".join).unstack().reindex(columns=["ROY", "DPOY"]))
    pd.set_option("display.max_rows", 100)
    print(table.fillna("—").to_string())

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{len(failures)} CHECK(S) FAILED: {failures}'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
