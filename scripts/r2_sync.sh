#!/usr/bin/env bash
# Sync private listening data (DATA_DIR, CACHE_DIR, MUSIC_DB) with a Cloudflare R2 bucket.
#
# Usage:
#   bash scripts/r2_sync.sh pull [--all | --raw | --cache | --db]
#   bash scripts/r2_sync.sh push [--all | --raw | --cache | --db]
#
# Requires: aws CLI (`brew install awscli`) and R2_* environment variables (or .env).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi

: "${R2_ACCOUNT_ID:?R2_ACCOUNT_ID is required}"
: "${R2_BUCKET:?R2_BUCKET is required}"
: "${R2_ACCESS_KEY_ID:?R2_ACCESS_KEY_ID is required}"
: "${R2_SECRET_ACCESS_KEY:?R2_SECRET_ACCESS_KEY is required}"

export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
export AWS_DEFAULT_REGION="auto"

ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
CACHE_DIR="${CACHE_DIR:-$HOME/.cache/music-story}"
MUSIC_DB="${MUSIC_DB:-${REPO_ROOT}/build/music.duckdb}"
DATA_DIR="${DATA_DIR:-}"

cmd="${1:-}"
shift || true

do_raw=false
do_cache=false
do_db=false

if [[ $# -eq 0 ]]; then
  do_raw=true
  do_cache=true
  do_db=true
else
  for flag in "$@"; do
    case "$flag" in
      --all)   do_raw=true; do_cache=true; do_db=true ;;
      --raw)   do_raw=true ;;
      --cache) do_cache=true ;;
      --db)    do_db=true ;;
      *) echo "Unknown option: $flag" >&2; exit 2 ;;
    esac
  done
fi

aws_r2() {
  aws s3 "$@" --endpoint-url "$ENDPOINT"
}

r2_exists() {
  aws s3 ls "$1" --endpoint-url "$ENDPOINT" >/dev/null 2>&1
}

case "$cmd" in
  pull)
    if $do_raw; then
      : "${DATA_DIR:?DATA_DIR is required to pull raw data}"
      mkdir -p "$DATA_DIR"
      echo "Pulling raw exports -> $DATA_DIR"
      aws_r2 sync "s3://${R2_BUCKET}/raw/" "$DATA_DIR/" --exclude ".DS_Store"
    fi
    if $do_cache; then
      mkdir -p "$CACHE_DIR"
      if r2_exists "s3://${R2_BUCKET}/cache/http_cache.sqlite"; then
        echo "Pulling HTTP cache -> $CACHE_DIR/http_cache.sqlite"
        aws_r2 cp "s3://${R2_BUCKET}/cache/http_cache.sqlite" "${CACHE_DIR}/http_cache.sqlite"
      else
        echo "No http_cache.sqlite in R2 yet; skipping."
      fi
    fi
    if $do_db; then
      mkdir -p "$(dirname "$MUSIC_DB")"
      if r2_exists "s3://${R2_BUCKET}/build/music.duckdb"; then
        echo "Pulling DuckDB -> $MUSIC_DB"
        aws_r2 cp "s3://${R2_BUCKET}/build/music.duckdb" "$MUSIC_DB"
      else
        echo "No music.duckdb in R2 yet; skipping."
      fi
    fi
    ;;
  push)
    if $do_raw; then
      : "${DATA_DIR:?DATA_DIR is required to push raw data}"
      echo "Pushing raw exports from $DATA_DIR -> s3://${R2_BUCKET}/raw/"
      aws_r2 sync "$DATA_DIR/" "s3://${R2_BUCKET}/raw/" --exclude ".DS_Store" --exclude "*.tmp"
    fi
    if $do_cache; then
      cache_file="${CACHE_DIR}/http_cache.sqlite"
      if [[ -f "$cache_file" ]]; then
        if command -v sqlite3 >/dev/null 2>&1; then
          sqlite3 "$cache_file" "PRAGMA wal_checkpoint(TRUNCATE); PRAGMA quick_check;" >/dev/null
        fi
        echo "Pushing HTTP cache -> s3://${R2_BUCKET}/cache/http_cache.sqlite"
        aws_r2 cp "$cache_file" "s3://${R2_BUCKET}/cache/http_cache.sqlite"
      else
        echo "No local $cache_file to push; skipping."
      fi
    fi
    if $do_db; then
      if [[ -f "$MUSIC_DB" ]]; then
        echo "Pushing DuckDB -> s3://${R2_BUCKET}/build/music.duckdb"
        aws_r2 cp "$MUSIC_DB" "s3://${R2_BUCKET}/build/music.duckdb"
      else
        echo "No local $MUSIC_DB to push; skipping."
      fi
    fi
    ;;
  *)
    echo "Usage: $0 {pull|push} [--all | --raw | --cache | --db]" >&2
    exit 2
    ;;
esac
