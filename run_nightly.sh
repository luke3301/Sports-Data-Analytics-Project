#!/bin/bash
# Nightly MVP update: download live DARKO DPM, run both models + Dominance Index, save to TiDB.
# Run by launchd (launchd/com.lukeshoe.mvp-nightly.plist) at 3:00 AM; safe to run by hand too.
# Each day's output goes to logs/nightly_YYYY-MM-DD.log (appended if run more than once a day).

set -uo pipefail

PROJECT_DIR="/Users/lukeshoe/Sports-Data-Analytics-Project"
PYTHON="$PROJECT_DIR/venv/bin/python"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/nightly_$(date +%Y-%m-%d).log"
KEEP_LOG_DAYS=30

mkdir -p "$LOG_DIR"
exec >>"$LOG_FILE" 2>&1   # everything below, including Python output, goes to today's log
cd "$PROJECT_DIR" || exit 1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

log "===== nightly run started ====="

# After waking from sleep the network can take a minute to come back; wait up to 5 minutes.
for i in $(seq 1 30); do
    if /usr/bin/curl -s -m 10 -o /dev/null https://www.darko.app/; then
        break
    fi
    if [ "$i" -eq 30 ]; then
        log "FAILED: no network after 5 minutes"
        exit 1
    fi
    sleep 10
done

log "downloading live DARKO DPM ..."
if ! "$PYTHON" download_darko.py; then
    log "FAILED: download_darko.py (darko_live.csv left unchanged; predictions not run)"
    exit 1
fi

log "running models and saving to TiDB ..."
if ! "$PYTHON" compare_models.py --save-db; then
    log "FAILED: compare_models.py --save-db"
    exit 1
fi

# Prune old nightly logs (only files matching nightly_*.log inside logs/)
find "$LOG_DIR" -name 'nightly_*.log' -type f -mtime +"$KEEP_LOG_DAYS" -delete

log "===== nightly run finished OK ====="
