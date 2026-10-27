# System Specification & Contracts

Full detail: [docs/PROJECT.md](../docs/PROJECT.md) (data facts, pipeline, enrichment and quota
strategy, decision log) and [STATE.md](../STATE.md) (wave status, next steps). The table contract is
`sql/schema.sql`, guarded by `tests/test_schema.py`. This file restates the invariants a reviewer
needs without opening those files.

## 1. Core Scope & MVP Boundaries
- **Input:** Spotify Extended Streaming History (130,513 rows, Jul 2011 to Oct 2026) and the
  Last.fm CSV (114,332 scrobbles, Apr 2007 to Oct 2026). Both stay on Charlie's machine.
- **Pipeline:** `uv run python -m pipeline.build_pipeline [--fixtures]` runs steps 00-07 into one
  DuckDB file: ingest, normalise + match (Gate 1: at least 95% of 2023-26 scrobbles matched; passed
  at 95.81%), enrichment parse, dims, sessions, genre, marts.
- **Site:** Observable Framework static build (`site/`), pages index, artists, songs, genres, habits,
  places, explorer. Deployed as Workers static assets at music.charliechonguyen.com behind
  Cloudflare Access. The data loaders read `SITE_DB` when set, else the fixture marts.
- **Current wave (from STATE.md "Next"):** the daily `enrich fetch` runs on Charlie's Mac until
  Spotify finishes. Then: real `build_pipeline`, site build with `SITE_DB=build/music.duckdb`,
  deploy.

### Enrichment state contract (implemented in `pipeline/enrich*.py`, PRs #1-#3)
- **Idempotent and resumable.** Every HTTP response is stored in the SQLite cache
  (`sql/cache_schema.sql`) as it arrives, and work items stay queued until they succeed. A rerun of
  `fetch` skips cached items and resumes from the queue, so an interrupted run never refetches.
- **429 handling.** `QUOTA_EXCEEDED` pauses the API at once for `Retry-After` (24 h if missing). A
  Spotify 429 without `Retry-After` pauses 1 h. Any `Retry-After` over 600 s pauses. Shorter waits
  are slept and retried. Every pause is written to `api_pause` with its reason and no request is
  sent to that API until it ends. Failed items retry once on the next `fetch`.
- **Spotify budget.** At most `SPOTIFY_DAILY_BUDGET` (default 500) requests per rolling 24 h,
  counted in `request_log`; only tracks with at least `--spotify-min-plays` (default 3) plays.
- **Exit when paused.** `fetch` exits with the resume time when only paused APIs remain.

### Site payload budget
- Workers static assets reject any file over 25 MiB. `plays_explorer.parquet` (Zstd, sorted so
  repeated names compress, explorer columns only) must stay under **20 MiB**. Fixture: 612 KB for
  59k rows, about linear in rows, so the real file is expected near 2-3 MB. The build must fail
  rather than ship an oversized file (Slice 4).
- DuckDB-Wasm loads from jsDelivr on the explorer page only, because the self-hosted wasm files are
  34-39 MiB. Only library code comes from CDNs; data stays behind Access.

## 2. Strictly Out of Scope ("Do NOT Build" List)
- No raw exports or databases in the repo or any prompt (including `/prep-audit` packets).
- No schema changes without the lead updating `tests/test_schema.py` and `STATE.md`.
- No public URLs: `workers_dev` and `preview_urls` stay off.
- No server code: the Worker is assets-only, so there is no runtime, database client or secret at
  the edge.

## 3. Data Models & Module Boundaries
- `sql/` schema + SQL steps, `pipeline/` Python steps (normalisation only in `normalize.py`),
  `site/` Observable Framework site, `specs/` work-packet specs.
- **Tables (`sql/schema.sql`) and primary keys:**
  - Raw and staging: `raw_spotify`, `raw_lastfm`, `stg_spotify` (`sp_id`), `stg_lastfm` (`lfm_id`),
    `lfm_self_dupes` (`lfm_id`).
  - Matching: `match_links`, `events` (`event_id`), `track_uri_map` (`track_uri`), `track_key_map`
    (`artist_norm`, `full_norm`).
  - Enrichment parse: `enr_local_duration` (`track_uri`), `enr_spotify_track` (`track_uri`),
    `enr_spotify_artist` (`spotify_artist_id`), `enr_mb_recording` (`lookup_kind`, `lookup_key`),
    `enr_mb_artist` (`artist_mbid`), `enr_lastfm_tags` (`entity_type`, `entity_key`, `tag`),
    `enr_lastfm_info` (`entity_type`, `entity_key`), `enr_deezer_track` (`isrc`),
    `enr_deezer_match` (`lookup_key`).
  - Dimensions: `dim_artist` (`artist_id`), `dim_album` (`album_id`), `dim_track` (`track_id` =
    ISRC, else `artist_norm::full_norm`), `bridge_track_artist` (`track_id`, `artist_id`, `role`).
  - Facts: `sessions` (`session_id`), `plays` (`play_id` = `events.event_id`), `skips`.
  - Genre: `genre_map` (`tag`), `track_genre` (`track_id`, `parent_genre`, `style`).
- **Marts:** `sql/marts/10_simple.sql`, `20_trap.sql`, `30_labels.sql`, `40_explorer.sql`
  (`explorer_plays` view feeding the Parquet export).
- **Slice split rule:** pipeline work (`sql/`, `pipeline/`, `tests/`) is `[CORE / DATA]` and verified
  with `uv run pytest -q` + `uv run ruff check`. Page work (`site/src/*.md`,
  `site/observablehq.config.js`) is a separate `[UI / VISUAL]` slice verified with
  `cd site && npm run build`.
