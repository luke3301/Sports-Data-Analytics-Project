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

    print("\nAward winners by season (ROY, DPOY):")
    table = (w[w.award.isin(["ROY", "DPOY"])].groupby(["season_id", "award"])["player"]
             .agg(" & ".join).unstack().reindex(columns=["ROY", "DPOY"]))
    pd.set_option("display.max_rows", 100)
    print(table.fillna("—").to_string())

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{len(failures)} CHECK(S) FAILED: {failures}'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
