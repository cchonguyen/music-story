-- 01_ingest.sql (W1): raw loaders, staging and Last.fm self-dedupe.
-- Re-runnable: clears the five tables it fills before loading.
-- Input: getvariable('data_dir') holds Spotify Streaming_History_*.json and recenttracks-*.csv.
-- Normalisation columns stay NULL here; pipeline/normalize.py fills them later.

DELETE FROM raw_spotify;
DELETE FROM raw_lastfm;
DELETE FROM stg_spotify;
DELETE FROM stg_lastfm;
DELETE FROM lfm_self_dupes;

-- Layer 1: every Spotify event, audio and video. ip_addr is deliberately not selected.
INSERT INTO raw_spotify
SELECT
    parse_filename(filename)                                          AS source_file,
    starts_with(parse_filename(filename), 'Streaming_History_Video_') AS is_video,
    CAST(CAST(ts AS TIMESTAMPTZ) AT TIME ZONE 'UTC' AS TIMESTAMP)     AS ts,
    platform,
    ms_played,
    conn_country,
    master_metadata_track_name,
    master_metadata_album_artist_name,
    master_metadata_album_album_name,
    spotify_track_uri,
    episode_name,
    episode_show_name,
    spotify_episode_uri,
    audiobook_title,
    audiobook_uri,
    audiobook_chapter_uri,
    audiobook_chapter_title,
    reason_start,
    reason_end,
    shuffle,
    skipped,
    offline,
    offline_timestamp,
    incognito_mode
FROM read_json(
    [getvariable('data_dir') || '/Streaming_History_Audio_*.json',
     getvariable('data_dir') || '/Streaming_History_Video_*.json'],
    format = 'array',
    filename = true,
    columns = {
        'ts': 'VARCHAR',
        'platform': 'VARCHAR',
        'ms_played': 'BIGINT',
        'conn_country': 'VARCHAR',
        'master_metadata_track_name': 'VARCHAR',
        'master_metadata_album_artist_name': 'VARCHAR',
        'master_metadata_album_album_name': 'VARCHAR',
        'spotify_track_uri': 'VARCHAR',
        'episode_name': 'VARCHAR',
        'episode_show_name': 'VARCHAR',
        'spotify_episode_uri': 'VARCHAR',
        'audiobook_title': 'VARCHAR',
        'audiobook_uri': 'VARCHAR',
        'audiobook_chapter_uri': 'VARCHAR',
        'audiobook_chapter_title': 'VARCHAR',
        'reason_start': 'VARCHAR',
        'reason_end': 'VARCHAR',
        'shuffle': 'BOOLEAN',
        'skipped': 'BOOLEAN',
        'offline': 'BOOLEAN',
        'offline_timestamp': 'BIGINT',
        'incognito_mode': 'BOOLEAN'
    }
);

-- Layer 1: every Last.fm scrobble.
INSERT INTO raw_lastfm
SELECT uts, utc_time, artist, artist_mbid, album, album_mbid, track, track_mbid
FROM read_csv(
    getvariable('data_dir') || '/recenttracks-*.csv',
    header = true,
    columns = {
        'uts': 'BIGINT',
        'utc_time': 'VARCHAR',
        'artist': 'VARCHAR',
        'artist_mbid': 'VARCHAR',
        'album': 'VARCHAR',
        'album_mbid': 'VARCHAR',
        'track': 'VARCHAR',
        'track_mbid': 'VARCHAR'
    }
);

-- Layer 2a: music events only (track URI present, not video).
INSERT INTO stg_spotify
SELECT
    row_number() OVER (ORDER BY ts, spotify_track_uri, ms_played, source_file) AS sp_id,
    ts - to_milliseconds(ms_played)                                           AS started_at_utc,
    ts                                                                        AS ended_at_utc,
    ms_played,
    ms_played >= 30000                                                        AS is_full_listen,
    spotify_track_uri                                                         AS track_uri,
    master_metadata_album_artist_name                                         AS artist_raw,
    master_metadata_track_name                                                AS track_raw,
    master_metadata_album_album_name                                          AS album_raw,
    platform                                                                  AS platform_raw,
    CASE
        WHEN lower(platform) LIKE '%ios%' OR lower(platform) LIKE '%iphone%' OR lower(platform) LIKE '%ipad%' THEN 'ios'
        WHEN platform LIKE 'Android%' THEN 'android'
        WHEN platform LIKE 'Windows%' THEN 'windows'
        WHEN platform LIKE 'OS X%' OR platform LIKE 'osx%' THEN 'mac'
        WHEN platform LIKE 'Linux%' THEN 'linux'
        WHEN platform LIKE 'WebPlayer%' OR platform LIKE 'web_player%' THEN 'web'
        WHEN platform LIKE 'cast%' OR platform LIKE 'Partner google%' THEN 'cast'
        WHEN platform LIKE 'Partner%' THEN 'partner'
        ELSE 'other'
    END                                                                       AS platform_family,
    conn_country                                                              AS country_raw,
    NULLIF(reason_start, '')                                                  AS reason_start,
    NULLIF(reason_end, '')                                                    AS reason_end,
    shuffle,
    skipped,
    offline,
    incognito_mode                                                            AS incognito,
    NULL::VARCHAR AS artist_norm,
    NULL::VARCHAR AS full_norm,
    NULL::VARCHAR AS base_norm,
    NULL::VARCHAR AS mix_desc
FROM raw_spotify
WHERE spotify_track_uri IS NOT NULL AND NOT is_video;

-- Layer 2b: Last.fm ids are assigned over all raw rows before dedupe, so they never shift.
CREATE OR REPLACE TEMP TABLE _lfm_numbered AS
SELECT
    row_number() OVER (ORDER BY uts, artist, track, album) AS lfm_id,
    uts, utc_time, artist, artist_mbid, album, album_mbid, track, track_mbid
FROM raw_lastfm;

-- Self-dedupe: compare each scrobble with the previous one of the same raw (artist, track),
-- even when that previous one was itself a dupe.
CREATE OR REPLACE TEMP TABLE _lfm_flagged AS
SELECT
    *,
    lag(uts) OVER w AS prev_uts,
    lag(lfm_id) OVER w AS prev_lfm_id
FROM _lfm_numbered
WINDOW w AS (PARTITION BY artist, track ORDER BY uts, lfm_id);

INSERT INTO lfm_self_dupes
SELECT lfm_id, prev_lfm_id AS kept_lfm_id, CAST(uts - prev_uts AS DOUBLE) AS gap_sec
FROM _lfm_flagged
WHERE prev_uts IS NOT NULL AND uts - prev_uts <= 60;

-- Layer 2c: remaining scrobbles, scrobble time as naive UTC.
INSERT INTO stg_lastfm
SELECT
    f.lfm_id,
    CAST(to_timestamp(f.uts) AT TIME ZONE 'UTC' AS TIMESTAMP) AS scrobbled_at_utc,
    f.artist AS artist_raw,
    f.track AS track_raw,
    f.album AS album_raw,
    NULLIF(f.artist_mbid, '') AS artist_mbid,
    NULLIF(f.album_mbid, '') AS album_mbid,
    NULLIF(f.track_mbid, '') AS track_mbid,
    NULL::VARCHAR AS artist_norm,
    NULL::VARCHAR AS full_norm,
    NULL::VARCHAR AS base_norm,
    NULL::VARCHAR AS mix_desc
FROM _lfm_flagged f
WHERE f.lfm_id NOT IN (SELECT lfm_id FROM lfm_self_dupes);

DROP TABLE _lfm_flagged;
DROP TABLE _lfm_numbered;
