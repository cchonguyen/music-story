# W6: trap marts

Tier: Opus (maxTurns 40). Deliverable: `sql/marts/20_trap.sql` (one file, DuckDB SQL).
Each mart here has a tempting wrong answer. The acceptance test uses the fixture's named scenarios
(`fixture_scenarios`) to catch it.

## Read only
- `sql/schema.sql` Layers 5-7 (dim_artist, dim_track, bridge_track_artist, plays, skips, sessions)
- `tests/test_marts_trap_fixture.py` and `tests/mart_helpers.py` (your acceptance test; do not edit)

## Rules
- Inputs are the tables above, already built. Never read events, stg_* or raw_*.
- Every table is `CREATE OR REPLACE TABLE mart_* AS ...`. No views or temp tables left behind.
- `year` is always `year(started_at_local)`. Columns exactly in the order listed.
- Must not depend on `10_simple.sql` (W5); both files run independently in name order.

## Tables
1. `mart_artist_arc(artist_id, plays, first_year, last_year, years_active, longest_gap_years,
   comeback_year, peak_year, peak_share)`: one row per artist with plays. longest_gap_years = most
   consecutive years with no plays between two active years (0 if none). comeback_year = the first
   active year that follows a gap of >= 3 years, else NULL. peak_year = year with most plays (ties:
   earliest). peak_share = peak-year plays / plays. Trap: last_year - first_year is not years_active.
2. `mart_binge(track_id, window_start, window_plays, lifetime_plays, rate_ratio)`: one row per track
   with >= 10 plays. Windows are rolling 14 local days `[d, d + 14)` starting on any day the track was
   played; keep the window with most plays (ties: earliest). rate_ratio = window_plays /
   (lifetime_plays * 14 / span_days), span_days = greatest(14, last play day - first play day + 1).
   Trap: calendar fortnights or months split a binge in two.
3. `mart_remixer_year(artist_id, year, remix_plays, original_plays)`: for artists with role 'remixer'
   in bridge_track_artist. remix_plays = plays of tracks they remixed; original_plays = plays of the
   non-remix tracks (`NOT is_remix`) sharing those tracks' work_id. Rows where either is > 0.
   Trap: crediting by primary artist misses the remixer entirely.
4. `mart_song_age(year, age_bucket, plays)`: age = year - dim_track.work_year. Buckets '0' (<= 0),
   '1-2', '3-5', '6-10', '11-20', '21+', and 'unknown' when work_year is NULL. Trap: recording_year
   makes a 2021 remaster of a 2008 song look new.
5. `mart_skip_rate(year, skips, spotify_plays, skip_rate)`: years >= 2012 only. spotify_plays = plays
   with source <> 'lastfm'; skip_rate = skips / (skips + spotify_plays). Trap: Last.fm-only plays
   can never be skips, so they must not dilute the rate.
6. `mart_sessions_year(year, sessions, median_minutes, p90_minutes, sessions_10, sessions_30)`:
   minutes from UTC start/end (`quantile_cont` for p90). sessions_10 / sessions_30 = count of
   new_session_10 / new_session_30 flags over plays AND skips that year. Trap: local times jump at DST.
7. `mart_country_year(year, country, plays, imputed_plays)`: NULL country becomes 'unknown';
   imputed_plays counts country_imputed.

## Done when
`uv run pytest tests/test_marts_trap_fixture.py` passes (skipped until the file exists), then the full
suite and `uv run ruff check` are green.
