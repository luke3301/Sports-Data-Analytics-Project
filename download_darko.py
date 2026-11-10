"""
Download the live DARKO DPM leaderboard (current season) from https://www.darko.app/.

The site builds its CSV in the browser (a JavaScript blob), so a plain HTTP request can't fetch it.
This script drives headless Chromium with Playwright: it loads the page, waits for the network to go
idle and for the player table and CSV button to render, clicks the button and captures the download.

Output: data/raw/darko_live.csv. That is the only file this script replaces. The download goes to a
temporary data/raw/darko_live.csv.part first, is validated, and only then atomically renamed over
darko_live.csv, so a failed or partial download never clobbers the previous good copy. Historical
darko_<season>.csv files are never opened, moved or deleted.

Usage:
    python download_darko.py            # headless
    python download_darko.py --headed   # watch the browser (debugging)
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

URL = "https://www.darko.app/"
RAW_DIR = Path(__file__).parent / "data" / "raw"
OUT_PATH = RAW_DIR / "darko_live.csv"
TMP_PATH = RAW_DIR / "darko_live.csv.part"

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
CSV_BUTTON = "button.tool-action--csv"        # the toolbar "CSV" button (aria-label "Download CSV")
TABLE_ROWS = "table tbody tr"
MIN_ROWS = 300                                # a full NBA leaderboard has ~450-550 players
REQUIRED_COLUMNS = {"Player", "DPM"}
TIMEOUT_MS = 60_000
ATTEMPTS = 2


def fetch_csv(dest: Path, headed: bool = False) -> str:
    """Load darko.app, wait for the data to hydrate, click CSV and save the download to `dest`."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        try:
            context = browser.new_context(user_agent=USER_AGENT, viewport={"width": 1440, "height": 900},
                                          locale="en-US", accept_downloads=True)
            page = context.new_page()
            page.goto(URL, wait_until="networkidle", timeout=TIMEOUT_MS)

            # Don't click until the JavaScript app has rendered the board and its toolbar
            page.locator(TABLE_ROWS).first.wait_for(state="visible", timeout=TIMEOUT_MS)
            button = page.locator(CSV_BUTTON)
            if button.count() == 0:  # fallback if the class name ever changes
                button = page.get_by_role("button", name="Download CSV").filter(visible=True)
            button.first.wait_for(state="visible", timeout=TIMEOUT_MS)
            page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)

            with page.expect_download(timeout=TIMEOUT_MS) as download_info:
                button.first.click()
            download = download_info.value
            if download.failure():
                raise RuntimeError(f"download failed: {download.failure()}")
            download.save_as(dest)
            return download.suggested_filename
        finally:
            browser.close()


def validate(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"downloaded CSV is missing columns {sorted(missing)}; got {list(df.columns)[:10]}")
    if len(df) < MIN_ROWS:
        raise ValueError(f"downloaded CSV has only {len(df)} rows (expected >= {MIN_ROWS})")
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    a = ap.parse_args()
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, ATTEMPTS + 1):
        try:
            name = fetch_csv(TMP_PATH, headed=a.headed)
            df = validate(TMP_PATH)
            break
        except (PlaywrightTimeout, RuntimeError, ValueError) as e:
            TMP_PATH.unlink(missing_ok=True)  # only ever our own temp file
            if attempt == ATTEMPTS:
                raise SystemExit(f"DARKO download failed after {ATTEMPTS} attempts: {e}\n"
                                 f"Existing {OUT_PATH.name} (if any) was left unchanged.")
            print(f"  attempt {attempt} failed ({type(e).__name__}: {str(e)[:100]}); retrying in 10s ...")
            time.sleep(10)

    os.replace(TMP_PATH, OUT_PATH)  # atomic: darko_live.csv is either the old file or the new one
    as_of = ""
    if "Market as of" in df.columns:  # some rows hold a "—" placeholder instead of a date
        latest = pd.to_datetime(df["Market as of"], errors="coerce").max()
        as_of = f", market as of {latest:%Y-%m-%d}" if pd.notna(latest) else ""
    print(f"Saved {len(df)} players -> {OUT_PATH} (site file: {name}{as_of}; "
          f"downloaded {datetime.now():%Y-%m-%d %H:%M})")


if __name__ == "__main__":
    main()
