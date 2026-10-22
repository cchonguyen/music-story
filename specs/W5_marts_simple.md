# W5: simple marts

Tier: Haiku (maxTurns 20). Deliverable: `sql/marts/10_simple.sql` (one file, DuckDB SQL).

## Read only
- `sql/schema.sql` Layers 5-7 (dim_track, plays, skips, sessions, track_genre)
- `tests/test_marts_simple_fixture.py` and `tests/mart_helpers.py` (your acceptance test; do not edit)

## Rules
- Inputs are the tables above, already built. Never read events, stg_* or raw_*.
- Every table is `CREATE OR REPLACE TABLE mart_* AS ...`, so the file is re-runnable.
- `year` is always `year(started_at_local)` (local time, not UTC). Hours = `sum(ms_imputed) / 3.6e6`.
- Columns exactly in the order listed. No views, no temp tables left behind.

## Tables
1. `mart_year(year, plays, skips, listen_hours, artists, tracks, new_artists, new_tracks, sessions)`:
   one row per year with plays. skips from `skips`, sessions from `sessions` (both by their own local
   year, 0 when none). artists / tracks = distinct ids that year. new_artists / new_tracks = ids whose
   first play (earliest started_at_utc) falls in that year.
2. `mart_artist_year(year, artist_id, plays, listen_hours, rank)`: every artist-year with plays.
   rank = row_number per year ordered by plays DESC, ms DESC, artist_id.
3. `mart_track_year(year, track_id, artist_id, plays, listen_hours, rank)`: same per track;
   artist_id = dim_track.primary_artist_id; ties broken by track_id.
4. `mart_clock(year, weekday, hour, plays)`: weekday = isodow (1 = Monday), hour 0-23, both local.
5. `mart_genre_year(year, parent_genre, style, plays_weighted)`: sum of track_genre.weight over plays.
6. `mart_platform_year(year, platform_family, plays)`: NULL platform_family becomes 'unknown'.

## Done when
`uv run pytest tests/test_marts_simple_fixture.py` passes (it is skipped until the file exists), then the
full suite and `uv run ruff check` are green.
