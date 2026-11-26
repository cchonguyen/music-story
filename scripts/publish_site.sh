#!/usr/bin/env bash
# One command to rebuild the data, build the site and deploy it to Cloudflare.
# Run from anywhere on the Mac:  bash /Users/charliechonguyen/Projects/music-story/music-story/scripts/publish_site.sh
set -euo pipefail

REPO="/Users/charliechonguyen/Projects/music-story/music-story"
DB="$REPO/build/music.duckdb"

cd "$REPO"

echo "== 1/3 Rebuild data (steps 05 onward)"
uv run python -m pipeline.build_pipeline --from 05

echo "== 2/3 Build site (skips the root prebuild that needs admin rights)"
cd "$REPO/site"
SITE_DB="$DB" npm run build

echo "== 3/3 Deploy to Cloudflare"
cd "$REPO"
npx wrangler deploy

echo "Done. Check https://music.charliechonguyen.com/artists"
