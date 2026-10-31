# W9c — Genre X-Ray, Hierarchy & Circadian Clock Marts

## Goal
Extend `sql/marts/50_insights.sql` and `pipeline/site_data.py` with three genre-lineage and rhythm marts (`mart_genre_xray`, `mart_genre_hierarchy`, `mart_genre_clock`) and a 20 MiB Cloudflare Workers Parquet size guard, while keeping `sql/marts/10_simple.sql` through `sql/marts/40_explorer.sql` untouched.

## Contracts

### 1. `mart_genre_xray` (`sql/marts/50_insights.sql`)
- **Primary Key (4-tuple):** `(artist_norm, title_norm, parent_genre, style)` matching `sql/marts/40_explorer.sql` lines 28–31 (`a.artist_norm`, `t.full_norm AS title_norm`, `g.parent_genre`, `g.style`).
- **Aggregation across member `track_id`s:** Distinct `track_id`s that share `(artist_norm, title_norm, parent_genre, style)` are collapsed into a single play-weighted row so that `explorer_plays LEFT JOIN mart_genre_xray USING (artist_norm, title_norm, parent_genre, style)` is strictly 1:1 (`post_join_rows == pre_join_rows` and `unmatched_classified == 0`).
- **Columns:**
  - `track_id VARCHAR`: representative `track_id` (most-played member `track_id`, tie-broken lexicographically)
  - `title VARCHAR`: representative display title
  - `artist VARCHAR`: representative display artist name
  - `artist_norm VARCHAR`: normalised artist key
  - `title_norm VARCHAR`: normalised title key (`dim_track.full_norm`)
  - `parent_genre VARCHAR`: primary parent genre from `track_genre`
  - `style VARCHAR`: primary style from `track_genre`
  - `primary_weight DOUBLE`: play-weighted average primary style weight (rounded to 4 decimals)
  - `level VARCHAR`: dominant tag level (`'track'`, `'album'`, or `'artist'`)
  - `secondary_styles VARCHAR`: comma-separated co-occurring styles and percentage weights on the representative track (or `''` when single-style)
  - `suppressed_umbrellas VARCHAR`: summary of umbrella disaggregation status (`'disaggregated -> ' || style` when `style <> parent_genre`, else `'umbrella retained (' || parent_genre || ')'`)
  - `plays BIGINT`: total non-skip plays across member tracks
  - `listen_hours DOUBLE`: total listen hours (`round(sum(ms_imputed) / 3.6e6, 2)`)
  - `skip_rate DOUBLE`: `round(skips / nullif(plays + skips, 0), 4)`
  - `peak_local_hour INTEGER`: modal `hour(started_at_local)` across member plays
  - `top_country VARCHAR`: modal `country` across member plays
  - `first_year INTEGER`: earliest `year(started_at_local)`
  - `last_year INTEGER`: latest `year(started_at_local)`

### 2. `mart_genre_hierarchy` (`sql/marts/50_insights.sql`)
- **Grain:** `(parent_genre, style, artist_id)` for top 15 artists per `(parent_genre, style)` ranked by weighted plays.
- **Columns:** `parent_genre`, `style`, `artist_id`, `artist`, `plays`, `plays_weighted`, `listen_hours`, `tracks`, `style_share_of_parent`, `artist_share_of_style`, `artist_rank_in_style`.

### 3. `mart_genre_clock` (`sql/marts/50_insights.sql`)
- **Grain:** `(parent_genre, style, weekday_type, hour)` using `plays.started_at_local` (`hour(started_at_local) BETWEEN 0 AND 23`, `weekday_type IN ('all', 'weekday', 'weekend')` via `isodow(started_at_local)`).
- **Columns:** `parent_genre`, `style`, `weekday_type`, `hour`, `plays`, `plays_weighted`, `listen_hours`.

### 4. Parquet Size Guard (`pipeline/site_data.py`)
- `MAX_PARQUET_BYTES = 20 * 1024 * 1024` (20 MiB, safely under the 25 MiB Cloudflare Workers static asset limit).
- `parquet_bytes()` raises `ValueError` if the generated `.parquet` file exceeds `MAX_PARQUET_BYTES`.

### 5. Fixture Mart Generator Parity (`scripts/generate_fixture_marts.py`)
- Adds `genre_xray`, `genre_hierarchy`, and `genre_clock` outputs after all existing RNG draws so `Gen(SEED=20260422)` RNG state parity with `scripts/make_fixtures.py` is preserved (`test_generate_fixture_marts_rng_parity`).
