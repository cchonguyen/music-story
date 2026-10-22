# W4: site skeleton and deploy config

Tier: Sonnet (maxTurns 30). Deliverables: `site/` (Observable Framework), `pipeline/site_data.py`,
`wrangler.jsonc`, `tests/test_site_data.py`. Never deploy, never run `wrangler login` or `wrangler deploy`.

## Read only
`pipeline/config.py`, `tests/mart_helpers.py`, `specs/W5_marts_simple.md` (table names and columns only),
this spec.

## Hosting (decided 2026-10-22)
Cloudflare Workers with static assets, not Pages: no public *.workers.dev or preview URL, so one
Cloudflare Access application on `music.charliechonguyen.com` covers everything.

`wrangler.jsonc` at the repo root: name `music-story`, a recent `compatibility_date`, assets-only
(`"assets": {"directory": "./site/dist", "not_found_handling": "404-page"}`, no `main`),
`"workers_dev": false`, `"preview_urls": false`,
`"routes": [{"pattern": "music.charliechonguyen.com", "custom_domain": true}]`.

## pipeline/site_data.py
- `mart_rows(name: str, db: Path | None = None) -> list[dict]`: rows of `mart_<name>` ordered by its
  first columns. With `db` (or env `SITE_DB`) it reads that DuckDB file read-only. Without either it
  builds the fixture marts in memory: `tests/mart_helpers.mart_db` logic (copy the INPUT_TABLES from
  dev_fixtures.duckdb, run every `sql/marts/*.sql` in name order). Move that logic into
  `pipeline/site_data.py` and make `tests/mart_helpers.py` import it, so there is one copy.
- CLI: `uv run python -m pipeline.site_data <name>` prints the rows as JSON to stdout (dates as ISO
  strings). This is what the site's data loaders call. Nothing else is printed.

## site/
- `site/package.json` with exact pinned versions of `@observablehq/framework` (current 1.x) and
  scripts `dev`, `build` (`observablehq build`). `site/package-lock.json` committed.
- `site/observablehq.config.js`: title "music-story", root `src`, output `dist`, no telemetry-dependent
  options, no external search or analytics.
- Data loaders `site/src/data/year.json.sh` and `site/src/data/clock.json.sh`, each one line:
  `cd ../.. && uv run python -m pipeline.site_data year` (resp. `clock`). Paths must work from the
  loader's working directory; check how Framework runs loaders.
- `site/src/index.md`: heading, one Plot bar chart of plays per year from `year.json`, a table of
  mart_year below it, and a weekday x hour heatmap from `clock.json` (all years summed).
- `.gitignore` already ignores `site/dist/`, `site/.observablehq/cache/`, `node_modules/`.

## Done when
- `tests/test_site_data.py` (you write it): `mart_rows('year')` on the fixture returns 20 rows with the
  mart_year columns; the CLI prints valid JSON; `SITE_DB` pointing at a small temp DuckDB file is honoured.
- `cd site && npm ci && npm run build` succeeds and `site/dist/index.html` exists.
- `uv run pytest` and `uv run ruff check` green. Report the Framework version and the build size.
