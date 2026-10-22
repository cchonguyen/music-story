# W7: dimensions and track identity

Tier: Opus, high effort (maxTurns 40). Deliverable: `pipeline/dims.py` with `run(con)` (build step 04).
You may add helpers to `pipeline/normalize.py` (e.g. `mix_credit`), but never change existing behaviour:
the golden normalize and match tests must stay green.

## Read only
- `sql/schema.sql` Layers 3-5 (events, enr_*, dim_*, bridge_track_artist, track_uri_map, track_key_map)
- `pipeline/normalize.py`, `tests/test_dims_fixture.py` (acceptance; do not edit), `tests/helpers.py`

## Rules
`run(con)` reads `events` and `enr_*` only, deletes then refills the six tables. Counts only on stdout.
Ids are deterministic: `artist_id` = row_number over artist_norm; `album_id` = row_number over
spotify_album_id. Must run in under 2 minutes on 250k events / 100k tracks: work on distinct keys.

1. Spotify tracks. For each distinct `events.track_uri`, with `enr_spotify_track` http 200: track_id = isrc.
   URIs sharing an ISRC are one track. Without an ISRC (404 / missing): the most common `track_mbid`
   of that URI's events -> `enr_mb_recording` (lookup_kind 'mbid') `isrcs[1]`; else the fallback key
   `artist_norm || '::' || full_norm` (most common among the URI's events). `track_uri_map` gets every URI.
2. Last.fm-only keys. For each distinct (artist_norm, full_norm) of events with `track_uri IS NULL`:
   (a) a Spotify-backed track whose events have the same key (several: most plays, then smallest
   track_id); else (b) `isrcs[1]` of the MB recording found by the key's most common track_mbid
   (lookup 'mbid'), or by lookup 'search' on the key with score >= 90; it joins a known track with
   that ISRC or becomes a new one; else (c) the fallback key. `track_key_map` holds every key seen in
   events (Spotify-backed keys map to their track).
3. `dim_track`: title = Spotify name, else most common track_raw. artist_norm / full_norm / base_norm /
   mix_desc = most common among the track's events (Spotify-backed first). isrc = track_id when it is
   an ISRC. is_remix = mix_desc present and not `is_generic_mix`. work_id = artist_norm::base_norm.
   duration_ms and duration_source by priority: spotify, local (`enr_local_duration`, max over URIs),
   musicbrainz (length_ms), lastfm (`enr_lastfm_info` track), deezer. recording_year = earliest year
   of every Spotify release_date of the track's URIs and MB first_release_date for its ISRC/MBID.
   work_year = min recording_year over the work_id. is_longform_mix = duration > 20 min, or > 10 min
   and full_norm has the word mix, set or live; false when duration is unknown. album_id = album of
   the most played URI. lastfm_listeners from `enr_lastfm_info` ('track', artist_norm::full_norm).
4. `dim_artist`: every artist_norm that is a primary, featured or remixer artist. name =
   `enr_spotify_artist.name`, else the most common artist_raw. spotify_artist_id = the id of the
   Spotify artist whose normalised name equals artist_norm (most common). artist_mbid = most common
   `events.artist_mbid`, else an MB artist credit with that name. type, country, begin_year,
   end_year from `enr_mb_artist`. lastfm_listeners from `enr_lastfm_info` ('artist', artist_norm).
5. `bridge_track_artist`: primary (position 1); featured = Spotify `artists[2..]` in order;
   remixer = `mix_credit(mix_desc)` (text before a trailing remix|mix|edit|rework|bootleg|flip|dub|vip
   word, normalised) when it equals a known artist_norm.
6. `dim_album`: one per `album_spotify_id` in 200 rows. name, album_type, release_date from Spotify;
   album_norm = `normalize_album(name)`; release_year = first 4 chars; primary_artist_id = most common
   first Spotify artist across its tracks; album_mbid NULL.

## Done when
`uv run pytest tests/test_dims_fixture.py` passes, the full suite and ruff are green. Report the counts
it prints on the fixture: tracks by id kind (isrc / mb isrc / fallback), artists, albums.
