# music-story

19.5 years of Spotify + Last.fm listening history -> DuckDB pipeline -> private static story site
(Observable Framework on Cloudflare Pages at music.charliechonguyen.com, behind Cloudflare Access).

Start every session by reading `STATE.md` (current wave, packet status, next command). Nothing else
is needed to resume.

## Rules
- Raw exports and databases never enter the repo or a prompt. Look at data through counts,
  DESCRIBE or SUMMARIZE; at most 10 sample rows, and only from `dev_fixtures.duckdb`.
- `sql/schema.sql` is the contract. Changing it means updating `tests/test_schema.py` and STATE.md
  in the same commit, and it is the lead's call, not a worker's.
- Tests define done. `uv run pytest` and `uv run ruff check` before every commit.
- Normalisation lives only in `pipeline/normalize.py`.
- Secrets live in `.env` (copied into worktrees by `.worktreeinclude`). Never echo them.

## Layout
- `sql/schema.sql` tables, `sql/cache_schema.sql` SQLite HTTP cache, `sql/NN_*.sql` SQL steps,
  `sql/marts/` analysis models
- `pipeline/` Python steps (`run(con)`), `pipeline/build_pipeline.py` runs them in order
- `scripts/make_fixtures.py` seeded fixture -> `fixtures/raw/` + `dev_fixtures.duckdb` (per worktree)
- `tests/golden/` hand-checked cases; `tests/test_*_fixture.py` packet acceptance tests
- `specs/Wn_*.md` one spec per work packet; `.claude/agents/*-worker.md` tiered workers

## Delegation (lead = Opus session)
Spawn workers with the Agent tool, `isolation: "worktree"`, at most 2-3 at once, passing only the spec
path. Worktrees branch from origin's default branch, so push main before a wave starts. Review each
branch, merge, update STATE.md. A packet that fails its tests twice moves up one tier.
