#!/bin/bash
# One enrichment pass for the Mac, run by launchd every 3 hours (see scripts/launchd/).
#
#   1. fetch: every API with queued work. Exits at once when every API is paused or the
#      Spotify budget is spent, and stops after --max-minutes at the latest.
#   2. build: steps 00-04 on the cache as it stands, so the marts and the dims coverage
#      line always match the latest fetch.
#
# Output goes to ~/Library/Logs/music-story-enrich.log, outside the repo. A lock directory
# stops two passes overlapping when one runs long.

set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
UV="${UV_BIN:-uv}"
LOG="$HOME/Library/Logs/music-story-enrich.log"
LOCK="$HOME/Library/Caches/music-story-enrich.lock"
MAX_MINUTES="${ENRICH_MAX_MINUTES:-170}"

mkdir -p "$(dirname "$LOG")" "$(dirname "$LOCK")"
if ! mkdir "$LOCK" 2>/dev/null; then
    echo "$(date '+%F %T') previous pass still running, skipping" >> "$LOG"
    exit 0
fi
trap 'rmdir "$LOCK"' EXIT

cd "$REPO" || exit 1
export PYTHONPATH="$REPO"

{
    echo "== $(date '+%F %T') fetch"
    "$UV" run python -m pipeline.enrich fetch --max-minutes "$MAX_MINUTES"
    echo "== $(date '+%F %T') status"
    "$UV" run python -m pipeline.enrich status
    echo "== $(date '+%F %T') build 00-04"
    "$UV" run python -m pipeline.build_pipeline --from 00 --to 04
    echo "== $(date '+%F %T') done"
} >> "$LOG" 2>&1
