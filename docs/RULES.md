# Working rules (music-story)

Moved from `CLAUDE.md` on 2026-11-03 (ADR-002). `CLAUDE.md` is now a shim that points here.

## Commands
- Unit tests: `uv run pytest -q`
- Python lint: `uv run ruff check`
- Site lint: `npm run lint`
- Site build (the typecheck for the site): `cd site && npm run build`
- Before any commit: `uv run pytest -q` and `uv run ruff check`. Tests define done.

## Rules
- Raw exports and databases never enter the repo or a prompt. Look at data through counts,
  DESCRIBE or SUMMARIZE; at most 10 sample rows, and only from `dev_fixtures.duckdb`.
- `sql/schema.sql` is the contract. Changing it means updating `tests/test_schema.py` and STATE.md
  in the same commit, and it is the lead's call, not a worker's.
- Normalisation lives only in `pipeline/normalize.py`.
- Secrets live in `.env` (copied into worktrees by `.worktreeinclude`). Never echo them.
- Before planning or changing architecture, read `docs/PROJECT.md` and follow its decisions, or say
  why one should change. A change that affects its facts, decisions or open items updates it in the
  same commit, next to STATE.md.

## Layout
- `sql/schema.sql` tables, `sql/cache_schema.sql` SQLite HTTP cache, `sql/NN_*.sql` SQL steps,
  `sql/marts/` analysis models
- `pipeline/` Python steps (`run(con)`), `pipeline/build_pipeline.py` runs them in order
- `scripts/make_fixtures.py` seeded fixture -> `fixtures/raw/` + `dev_fixtures.duckdb` (per worktree)
- `tests/golden/` hand-checked cases; `tests/test_*_fixture.py` packet acceptance tests
- `site/` Observable Framework site; loaders call `pipeline/site_data.py` (SITE_DB, else fixture marts)
- `specs/Wn_*.md` one spec per work packet; `.claude/agents/*-worker.md` tiered workers
- `docs/PROJECT.md` implementation notes: data facts, pipeline, enrichment and quota strategy, decisions

## Delegation (lead = Opus session)
Spawn workers with the Agent tool, `isolation: "worktree"`, at most 2-3 at once, passing only the spec
path. Worktrees branch from origin's default branch, so push main before a wave starts. Review each
branch, merge, update STATE.md. A packet that fails its tests twice moves up one tier.

## Deploy
- **Cloud (canonical):** Trigger **Actions → Cloud Pipeline & Deploy** (`.github/workflows/cloud-pipeline.yml`). It pulls `raw/`, `http_cache.sqlite`, and `music.duckdb` from the private Cloudflare R2 bucket, runs the pipeline, injects `CLOUDFLARE_SITE_DOMAIN` into `wrangler.jsonc`, and deploys behind Cloudflare Access. See `docs/CLOUD_SETUP.md`.
- **Local:** Pull latest R2 state first (`bash scripts/r2_sync.sh pull`) before pushing local data changes (`bash scripts/r2_sync.sh push`). For manual deploys, run `cd site && npm run build`, then `npx wrangler deploy` from the repo root (`wrangler.jsonc`: assets-only, `workers_dev` and `preview_urls` off, custom domain route). The Access app must exist before any deploy.
