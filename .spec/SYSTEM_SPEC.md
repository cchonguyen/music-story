# System Specification & Contracts

Full detail: [docs/PROJECT.md](../docs/PROJECT.md). Table contract: `sql/schema.sql`, guarded by
`tests/test_schema.py`. Working rules: `docs/RULES.md`. Wave status: `STATE.md`.

## 1. Core Scope
- **Input:** Spotify Extended Streaming History, Last.fm CSV, and manual genre override CSVs. Canonical copies of `raw/`, `http_cache.sqlite`, and `music.duckdb` live in a private Cloudflare R2 bucket (synced via `scripts/r2_sync.sh`) and never enter Git.
- **Pipeline:** `uv run python -m pipeline.build_pipeline [--fixtures]` runs steps 00-07 into one DuckDB
  file: ingest, normalise + match (Gate 1: at least 95% of 2023-26 scrobbles; passed at 95.81%),
  enrichment parse, dims, sessions, genre, track/artist overrides (`06b`), marts.
- **Site:** Observable Framework static build (`site/`), built and deployed by `.github/workflows/cloud-pipeline.yml` (or locally) as Workers static assets behind Cloudflare Access (`CLOUDFLARE_SITE_DOMAIN` injected at deploy time). Loaders read `SITE_DB` when set, else the fixture marts.
- **Enrichment contract:** idempotent and resumable; every HTTP response is cached; quota pauses are
  written to `api_pause`. Detail in `docs/PROJECT.md` section 5.
- **Payload budget:** Workers static assets reject files over 25 MiB. `plays_explorer.parquet` must
  stay under 20 MiB, and the build fails rather than ship a larger file.
- **Slice split:** pipeline work (`sql/`, `pipeline/`, `tests/`) is `[CORE / DATA]`, verified with
  `uv run pytest -q` and `uv run ruff check`. Page work (`site/src/*.md`) is `[UI / VISUAL]`, verified
  with `cd site && npm run build`.

## 2. Boundaries
Out-of-scope list: `.spec/boundaries/do-not-build.md`.

## 3. Module Boundaries
- `sql/` schema and SQL steps; `pipeline/` Python steps (normalisation only in `normalize.py`);
  `site/` Observable Framework site; `specs/` work-packet specs.
