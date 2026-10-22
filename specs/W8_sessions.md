# W8: plays, skips and sessions

Tier: Sonnet (maxTurns 30). Deliverable: `sql/05_sessions.sql` (build step 05, DuckDB SQL).

## Read only
`sql/schema.sql` Layers 2-6, `data/country_tz.csv`, `tests/test_sessions_fixture.py` (acceptance; do not
edit), `tests/helpers.py`.

## Rules
Re-runnable: delete from plays, skips, sessions first. Inputs: events, stg_spotify (by sp_id),
track_uri_map, track_key_map, dim_track, enr_spotify_track, dim_album, and the CSV at
`getvariable('country_tz_csv')`. Every events row becomes exactly one row of skips (is_skip) or plays,
with play_id = event_id.

1. Track: track_uri_map by track_uri, else track_key_map by (artist_norm, full_norm). artist_id =
   dim_track.primary_artist_id. album_id: URI -> enr_spotify_track.album_spotify_id ->
   dim_album.spotify_album_id, else dim_track.album_id.
2. ended_at_utc: events.ended_at_utc; Last.fm-only rows use started_at_utc + dim_track.duration_ms
   (210000 ms when unknown).
3. Country: Spotify-backed rows take stg_spotify.country_raw, with 'ZZ' or NULL meaning unknown.
   Over Spotify-backed rows in (started_at_utc, event_id) order, an unknown row takes the previous
   known country when the previous and next known rows agree and both are within 48 h of it
   (country_imputed = true). Last.fm-only rows: country NULL, not imputed.
4. tz from the CSV for coalesce(country, 'US'); a country missing from the CSV uses US's tz.
   started_at_local = started_at_utc in that zone, as a naive TIMESTAMP.
5. Sessions over ALL rows (plays and skips) in (started_at_utc, event_id) order. gap = started_at_utc
   minus the running MAX(ended_at_utc) of all earlier rows (not LAG). A row starts a session when it
   is first or gap > 20 min. session_id counts sessions from 1 in that order; session_index = position
   in the session from 1. new_session_10 / new_session_30: first row, or gap > 10 / 30 min.
6. median_completion = median(ms_played / duration_ms) over Spotify-backed events with ms_played >=
   30000, known duration and NOT is_longform_mix (ratio not capped). ms_imputed = ms_played, else
   floor(duration_ms * median_completion) (210000 ms when duration unknown). completion_ratio =
   least(ms_played / duration_ms, 1.0); NULL for Last.fm-only rows, unknown duration or longform.
7. platform_family, shuffle, offline, incognito, reason_start, reason_end, skipped come from
   stg_spotify; NULL for Last.fm-only rows. source, match_pass, match_gap_sec from events.
8. sessions: started_at_utc / started_at_local / tz of the first row, ended_at_utc = max end, n_plays,
   n_skips, listen_ms = sum of ms_imputed over plays and skips, platform_family = most common non-NULL
   (ties: the one that appears first in the session; NULL if none), sources = the one source if every
   row shares it, else 'mixed'.

## Done when
`uv run pytest tests/test_sessions_fixture.py` passes (skipped until the file exists); full suite and ruff
green. Report the session count and median_completion on the fixture.
