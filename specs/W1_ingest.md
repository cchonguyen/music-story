# W1: raw loaders and Last.fm self-dedupe

Tier: Haiku (maxTurns 20). Deliverable: `sql/01_ingest.sql`.

## Read only
- `sql/schema.sql`, sections Layer 1 and Layer 2 (raw_spotify, raw_lastfm, stg_spotify, stg_lastfm, lfm_self_dupes)
- `tests/test_ingest_fixture.py` (your acceptance test)

## Inputs
`getvariable('data_dir')` is a folder holding:
- `Streaming_History_Audio_*.json` and `Streaming_History_Video_*.json`: JSON arrays of objects with keys
  ts (`'2023-12-31T13:09:28Z'`), platform, ms_played, conn_country, ip_addr, master_metadata_track_name,
  master_metadata_album_artist_name, master_metadata_album_album_name, spotify_track_uri, episode_name,
  episode_show_name, spotify_episode_uri, audiobook_title, audiobook_uri, audiobook_chapter_uri,
  audiobook_chapter_title, reason_start, reason_end, shuffle, skipped, offline, offline_timestamp
  (null or epoch ms), incognito_mode.
- `recenttracks-*.csv`: header `uts,utc_time,artist,artist_mbid,album,album_mbid,track,track_mbid`,
  every field quoted. Empty fields must load as NULL (read_csv default).

## Rules
1. The file is re-runnable: start by deleting from the five tables it fills.
2. raw_spotify: every JSON row from both file families. Pass explicit `columns` types to `read_json`
   (do not rely on inference; offline_timestamp is null in most files). `source_file` is the file name
   only (`parse_filename`), `is_video` is true for Video files. `ts` parsed as UTC TIMESTAMP.
   ip_addr is never selected.
3. raw_lastfm: every CSV row, uts as BIGINT.
4. stg_spotify: raw rows with `spotify_track_uri IS NOT NULL AND NOT is_video`.
   `sp_id = row_number() OVER (ORDER BY ts, spotify_track_uri, ms_played, source_file)`,
   started_at_utc = ts - ms_played, ended_at_utc = ts, is_full_listen = ms_played >= 30000,
   empty reason_start / reason_end become NULL, norm columns stay NULL.
   platform_family from platform: `ios` -> ios; `Android%` -> android; `Windows%` -> windows;
   `OS X%` or `osx%` -> mac; `Linux%` -> linux; `WebPlayer%` or `web_player%` -> web;
   `cast%` or `Partner google%` -> cast; other `Partner%` -> partner; anything else -> other.
5. lfm ids: `lfm_id = row_number() OVER (ORDER BY uts, artist, track, album)` over ALL raw_lastfm rows.
6. Self-dedupe: within each (artist, track) pair of raw strings, ordered by (uts, lfm_id), a row whose
   uts minus the previous row's uts is <= 60 goes to lfm_self_dupes (kept_lfm_id = that previous row)
   and not to stg_lastfm. Compare with the previous row even if that row was itself a dupe.
7. stg_lastfm: the remaining rows, scrobbled_at_utc = to_timestamp(uts) as naive UTC.

## Done when
`uv run pytest tests/test_ingest_fixture.py` passes (it diffs your output against the fixture with
EXCEPT ALL in both directions), and `uv run pytest` and `uv run ruff check` stay green.
