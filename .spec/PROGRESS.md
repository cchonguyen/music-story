# Task Progress & Single-Slice Work Lock

> Rule: Mark only ONE task line at a time with the active work tag.
> `STATE.md` is the wave ledger; this file mirrors only the current wave's atomic tasks.

- [x] **Slice 3** `[CORE / DATA]`: Sync harness v2.2.0 from claude-harness-hub so `/prep-audit spec` appends linked and backticked references (PROJECT.md, STATE.md, schema) under `# APPENDED REFERENCES` — Target files: `.harness/scripts/bundle-handoff.mjs`, `.harness-version`, `.harness/hub.json`
- [ ] **Slice 4** `[CORE / DATA]`: Explorer Parquet size guard: `parquet_bytes` raises if the file exceeds 20 MiB; test covers the guard — Target files: `pipeline/site_data.py`, `tests/test_site_data.py`, `docs/PROJECT.md`
- [ ] **Slice 5** `[CORE / DATA]`: Real `build_pipeline` once the Spotify fetch completes (STATE.md Next 3); record counts and Gate checks — Target files: `STATE.md`, `docs/PROJECT.md`
- [ ] **Slice 6** `[UI / VISUAL]`: Real-data site build with `SITE_DB=build/music.duckdb` and deploy behind Access; re-verify Access redirects — Target files: `site/src/*.md`, `site/observablehq.config.js`, `STATE.md`
- [x] **Slice 1** `[CORE / DATA]`: Install harness v2.0 — Target files: `.claude/`, `.harness/`, `.spec/`, `CLAUDE.md`, `.gitignore`
- [x] **Slice 2** `[CORE / DATA]`: W10b explorer page (mixed scope; future waves split data and page slices) — Target files: `sql/marts/40_explorer.sql`, `pipeline/site_data.py`, `site/src/explorer.md`, `site/src/data/plays_explorer.parquet.sh`, `site/observablehq.config.js`, `tests/test_site_data.py`, `specs/W10b_explorer.md`, `docs/PROJECT.md`, `STATE.md`
