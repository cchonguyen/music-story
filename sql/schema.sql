-- schema.sql: the contract every packet builds against (W0).
--
-- Conventions
--   * All *_utc columns are naive TIMESTAMP values in UTC. *_local columns are
--     naive TIMESTAMP values in the play's local zone (column tz).
--   * Ids are BIGINT surrogates unless named *_uri, *_mbid or isrc.
--   * Norm columns (artist_norm, full_norm, base_norm, mix_desc) are produced
--     only by pipeline/normalize.py. Nothing else re-implements normalisation.
--   * Every statement is idempotent (CREATE OR REPLACE), so build_pipeline.py
--     can apply this file to a fresh or existing database.
--   * Changing a column here is a contract change: update tests/test_schema.py
--     and STATE.md in the same commit.

------------------------------------------------------------------------------
-- Layer 1: raw (written by sql/01_ingest.sql, W1)
------------------------------------------------------------------------------

-- One row per Spotify Streaming_History_Audio_*.json event. ip_addr is never
-- loaded. Video files are loaded too, flagged by is_video.
CREATE OR REPLACE TABLE raw_spotify (
    source_file                       VARCHAR NOT NULL,
    is_video                          BOOLEAN NOT NULL,
    ts                                TIMESTAMP NOT NULL,  -- UTC, when playback STOPPED
    platform                          VARCHAR,
    ms_played                         BIGINT NOT NULL,
    conn_country                      VARCHAR,
    master_metadata_track_name        VARCHAR,
    master_metadata_album_artist_name VARCHAR,
    master_metadata_album_album_name  VARCHAR,
    spotify_track_uri                 VARCHAR,
    episode_name                      VARCHAR,
    episode_show_name                 VARCHAR,
    spotify_episode_uri               VARCHAR,
    audiobook_title                   VARCHAR,
    audiobook_uri                     VARCHAR,
    audiobook_chapter_uri             VARCHAR,
    audiobook_chapter_title           VARCHAR,
    reason_start                      VARCHAR,
    reason_end                        VARCHAR,
    shuffle                           BOOLEAN,
    skipped                           BOOLEAN,
    offline                           BOOLEAN,
    offline_timestamp                 BIGINT,
    incognito_mode                    BOOLEAN
);

-- One row per line of the Last.fm recenttracks CSV. Empty fields load as NULL
-- (DuckDB read_csv default).
CREATE OR REPLACE TABLE raw_lastfm (
    uts         BIGINT NOT NULL,      -- epoch seconds UTC, scrobble time ~= track start
    utc_time    VARCHAR,
    artist      VARCHAR NOT NULL,
    artist_mbid VARCHAR,
    album       VARCHAR,
    album_mbid  VARCHAR,
    track       VARCHAR NOT NULL,
    track_mbid  VARCHAR
);

------------------------------------------------------------------------------
-- Layer 2: staging (01_ingest.sql creates rows; 02_match.py fills norm columns)
------------------------------------------------------------------------------

-- Music events only: raw_spotify rows with spotify_track_uri NOT NULL and
-- is_video = false. sp_id = row_number() OVER (ORDER BY ts, spotify_track_uri,
-- ms_played, source_file) so ids are stable across rebuilds.
CREATE OR REPLACE TABLE stg_spotify (
    sp_id           BIGINT PRIMARY KEY,
    started_at_utc  TIMESTAMP NOT NULL,   -- ts - ms_played
    ended_at_utc    TIMESTAMP NOT NULL,   -- ts
    ms_played       BIGINT NOT NULL,
    is_full_listen  BOOLEAN NOT NULL,     -- ms_played >= 30000
    track_uri       VARCHAR NOT NULL,
    artist_raw      VARCHAR,
    track_raw       VARCHAR,
    album_raw       VARCHAR,
    platform_raw    VARCHAR,
    platform_family VARCHAR,              -- ios|android|windows|mac|linux|web|cast|partner|other
    country_raw     VARCHAR,              -- conn_country as exported (may be 'ZZ')
    reason_start    VARCHAR,              -- '' becomes NULL
    reason_end      VARCHAR,              -- '' becomes NULL
    shuffle         BOOLEAN,
    skipped         BOOLEAN,
    offline         BOOLEAN,
    incognito       BOOLEAN,
    artist_norm     VARCHAR,              -- filled by 02_match.py
    full_norm       VARCHAR,
    base_norm       VARCHAR,
    mix_desc        VARCHAR
);

-- Last.fm after self-dedupe. lfm_id = row_number() OVER (ORDER BY uts,
-- artist, track, album) computed on raw_lastfm BEFORE dedupe, so ids never
-- shift when the dedupe rule changes.
CREATE OR REPLACE TABLE stg_lastfm (
    lfm_id           BIGINT PRIMARY KEY,
    scrobbled_at_utc TIMESTAMP NOT NULL,
    artist_raw       VARCHAR NOT NULL,
    track_raw        VARCHAR NOT NULL,
    album_raw        VARCHAR,
    artist_mbid      VARCHAR,             -- '' becomes NULL
    album_mbid       VARCHAR,
    track_mbid       VARCHAR,
    artist_norm      VARCHAR,             -- filled by 02_match.py
    full_norm        VARCHAR,
    base_norm        VARCHAR,
    mix_desc         VARCHAR
);

-- Audit: scrobbles removed by the self-dedupe rule (same raw artist and track
-- as the previous scrobble of that pair, at most 60 s later).
CREATE OR REPLACE TABLE lfm_self_dupes (
    lfm_id           BIGINT PRIMARY KEY,
    kept_lfm_id      BIGINT NOT NULL,     -- step 01: the earlier scrobble it duplicates;
                                          -- step 02 twins: the matched scrobble within 360 s
    gap_sec          DOUBLE NOT NULL
);

------------------------------------------------------------------------------
-- Layer 3: matching (02_match.py, W2)
------------------------------------------------------------------------------

-- One row per accepted Spotify <-> Last.fm pair. 1-to-1 on both sides.
CREATE OR REPLACE TABLE match_links (
    sp_id          BIGINT NOT NULL UNIQUE,
    lfm_id         BIGINT NOT NULL UNIQUE,
    match_pass     TINYINT NOT NULL,      -- 1 = full title, 2 = base title, 3 = equal names within 1 h
    match_gap_sec  DOUBLE NOT NULL,       -- scrobbled_at_utc - started_at_utc (signed)
    fuzzy_score    DOUBLE NOT NULL        -- 0..100, title score of the winning pass
);

-- One row per listening event from either source, before dimensions exist.
-- event_id = sp_id for Spotify-backed rows; 1e12 + lfm_id for Last.fm-only rows.
CREATE OR REPLACE TABLE events (
    event_id        BIGINT PRIMARY KEY,
    sp_id           BIGINT,
    lfm_id          BIGINT,
    source          VARCHAR NOT NULL,     -- both|spotify|lastfm
    started_at_utc  TIMESTAMP NOT NULL,   -- Spotify start when present, else scrobble time
    ended_at_utc    TIMESTAMP,            -- Spotify ts; NULL for lastfm until durations exist
    ms_played       BIGINT,               -- NULL for lastfm-only
    is_skip         BOOLEAN NOT NULL,     -- source = 'spotify' AND ms_played < 30000
    track_uri       VARCHAR,
    artist_raw      VARCHAR NOT NULL,     -- Spotify value when present
    track_raw       VARCHAR NOT NULL,
    album_raw       VARCHAR,
    artist_norm     VARCHAR NOT NULL,
    full_norm       VARCHAR NOT NULL,
    base_norm       VARCHAR NOT NULL,
    mix_desc        VARCHAR,
    track_mbid      VARCHAR,
    artist_mbid     VARCHAR,
    match_pass      TINYINT,
    match_gap_sec   DOUBLE
);

------------------------------------------------------------------------------
-- Layer 4: enrichment (03_enrich.py, W3). Parsed views of the HTTP cache.
-- The HTTP cache itself is SQLite, see sql/cache_schema.sql.
------------------------------------------------------------------------------

-- Duration observed locally: MAX(ms_played) over completed, unskipped plays
-- (reason_end = 'trackdone' AND NOT skipped).
CREATE OR REPLACE TABLE enr_local_duration (
    track_uri      VARCHAR PRIMARY KEY,
    duration_ms    BIGINT NOT NULL,
    n_completed    INTEGER NOT NULL
);

CREATE OR REPLACE TABLE enr_spotify_track (
    track_uri              VARCHAR PRIMARY KEY,
    isrc                   VARCHAR,
    name                   VARCHAR,
    duration_ms            BIGINT,
    explicit               BOOLEAN,
    album_spotify_id       VARCHAR,
    album_name             VARCHAR,
    album_type             VARCHAR,           -- album|single|compilation
    release_date           VARCHAR,           -- as returned: YYYY, YYYY-MM or YYYY-MM-DD
    release_date_precision VARCHAR,
    artists                STRUCT(id VARCHAR, name VARCHAR)[],
    http_status            INTEGER NOT NULL,  -- 404 rows are kept so they are not refetched
    fetched_at_utc         TIMESTAMP NOT NULL
);

CREATE OR REPLACE TABLE enr_spotify_artist (
    spotify_artist_id VARCHAR PRIMARY KEY,
    name              VARCHAR,
    genres            VARCHAR[],
    http_status       INTEGER NOT NULL,
    fetched_at_utc    TIMESTAMP NOT NULL
);

-- MusicBrainz recordings, keyed by how they were looked up.
CREATE OR REPLACE TABLE enr_mb_recording (
    lookup_kind       VARCHAR NOT NULL,       -- isrc|mbid|search
    lookup_key        VARCHAR NOT NULL,       -- the ISRC, MBID, or 'artist_norm::full_norm'
    recording_mbid    VARCHAR,
    title             VARCHAR,
    length_ms         BIGINT,
    isrcs             VARCHAR[],
    first_release_date VARCHAR,
    artist_credits    STRUCT(mbid VARCHAR, name VARCHAR, joinphrase VARCHAR)[],
    genres            VARCHAR[],
    score             INTEGER,                -- search score; NULL for direct lookups
    http_status       INTEGER NOT NULL,
    fetched_at_utc    TIMESTAMP NOT NULL,
    PRIMARY KEY (lookup_kind, lookup_key)
);

CREATE OR REPLACE TABLE enr_mb_artist (
    artist_mbid    VARCHAR PRIMARY KEY,
    name           VARCHAR,
    type           VARCHAR,
    country        VARCHAR,
    begin_year     INTEGER,
    end_year       INTEGER,
    genres         VARCHAR[],
    http_status    INTEGER NOT NULL,
    fetched_at_utc TIMESTAMP NOT NULL
);

-- Last.fm top tags. entity_key is 'artist_norm' for artists,
-- 'artist_norm::album_norm' for albums and 'artist_norm::full_norm' for tracks.
-- count is Last.fm's relative weight (0..100 within the entity).
CREATE OR REPLACE TABLE enr_lastfm_tags (
    entity_type    VARCHAR NOT NULL,          -- track|album|artist
    entity_key     VARCHAR NOT NULL,
    tag            VARCHAR NOT NULL,          -- lower-cased, trimmed
    count          INTEGER NOT NULL,
    fetched_at_utc TIMESTAMP NOT NULL,
    PRIMARY KEY (entity_type, entity_key, tag)
);

-- Last.fm global popularity, replaces Spotify popularity (removed Feb 2026).
CREATE OR REPLACE TABLE enr_lastfm_info (
    entity_type    VARCHAR NOT NULL,          -- track|artist
    entity_key     VARCHAR NOT NULL,
    mbid           VARCHAR,
    listeners      BIGINT,
    playcount      BIGINT,
    duration_ms    BIGINT,                    -- track only; 0 becomes NULL
    http_status    INTEGER NOT NULL,
    fetched_at_utc TIMESTAMP NOT NULL,
    PRIMARY KEY (entity_type, entity_key)
);

CREATE OR REPLACE TABLE enr_deezer_track (
    isrc           VARCHAR PRIMARY KEY,
    deezer_id      BIGINT,
    bpm            DOUBLE,                    -- 0 becomes NULL
    gain           DOUBLE,
    duration_ms    BIGINT,
    release_date   VARCHAR,
    http_status    INTEGER NOT NULL,
    fetched_at_utc TIMESTAMP NOT NULL
);

-- Deezer search by 'artist_norm::full_norm' (tracks under the Spotify play floor and Last.fm-only
-- songs), so ISRCs and albums do not depend on the Spotify quota. Only a hit whose normalised
-- artist and title equal the key counts; its /track/{id} lookup supplies ISRC and album.
CREATE OR REPLACE TABLE enr_deezer_match (
    lookup_key       VARCHAR PRIMARY KEY,     -- 'artist_norm::full_norm'
    deezer_id        BIGINT,                  -- NULL when no hit matched
    isrc             VARCHAR,
    album_deezer_id  BIGINT,
    album_name       VARCHAR,
    release_date     VARCHAR,                 -- YYYY-MM-DD
    duration_ms      BIGINT,
    http_status      INTEGER NOT NULL,        -- 404 when the search had no matching hit
    fetched_at_utc   TIMESTAMP NOT NULL
);

------------------------------------------------------------------------------
-- Layer 5: dimensions (04_dims.py, W7)
------------------------------------------------------------------------------

CREATE OR REPLACE TABLE dim_artist (
    artist_id          BIGINT PRIMARY KEY,
    name               VARCHAR NOT NULL,      -- display name, most common raw spelling
    artist_norm        VARCHAR NOT NULL UNIQUE,
    artist_mbid        VARCHAR,
    spotify_artist_id  VARCHAR,
    country            VARCHAR,
    artist_type        VARCHAR,
    begin_year         INTEGER,
    end_year           INTEGER,
    lastfm_listeners   BIGINT
);

CREATE OR REPLACE TABLE dim_album (
    album_id          BIGINT PRIMARY KEY,
    name              VARCHAR NOT NULL,
    album_norm        VARCHAR NOT NULL,
    primary_artist_id BIGINT,
    album_type        VARCHAR,                -- album|single|compilation|NULL
    release_date      VARCHAR,
    release_year      INTEGER,
    spotify_album_id  VARCHAR,
    album_mbid        VARCHAR
);

-- Recording-level identity. Remixes and edits with different durations are
-- separate tracks; versions of one composition share work_id.
CREATE OR REPLACE TABLE dim_track (
    track_id          VARCHAR PRIMARY KEY,    -- COALESCE(isrc, artist_norm || '::' || full_norm)
    isrc              VARCHAR,
    title             VARCHAR NOT NULL,       -- display title
    artist_norm       VARCHAR NOT NULL,       -- primary artist
    full_norm         VARCHAR NOT NULL,
    base_norm         VARCHAR NOT NULL,
    mix_desc          VARCHAR,
    is_remix          BOOLEAN NOT NULL,       -- mix_desc present and not generic
    work_id           VARCHAR NOT NULL,       -- artist_norm || '::' || base_norm
    primary_artist_id BIGINT NOT NULL,
    album_id          BIGINT,                 -- most-played album for this recording
    duration_ms       BIGINT,
    duration_source   VARCHAR,                -- spotify|local|musicbrainz|lastfm|deezer
    recording_year    INTEGER,                -- earliest release of this ISRC / MB recording
    work_year         INTEGER,                -- earliest recording_year across the work_id
    is_longform_mix   BOOLEAN NOT NULL,       -- > 20 min, or 10-20 min with mix|set|live keyword
    lastfm_listeners  BIGINT
);

CREATE OR REPLACE TABLE bridge_track_artist (
    track_id   VARCHAR NOT NULL,
    artist_id  BIGINT NOT NULL,
    role       VARCHAR NOT NULL,              -- primary|featured|remixer
    position   SMALLINT NOT NULL,             -- order within the role, from 1
    PRIMARY KEY (track_id, artist_id, role)
);

CREATE OR REPLACE TABLE track_uri_map (
    track_uri  VARCHAR PRIMARY KEY,
    track_id   VARCHAR NOT NULL
);

-- Resolves Last.fm-only events (no URI) to a track.
CREATE OR REPLACE TABLE track_key_map (
    artist_norm VARCHAR NOT NULL,
    full_norm   VARCHAR NOT NULL,
    track_id    VARCHAR NOT NULL,
    PRIMARY KEY (artist_norm, full_norm)
);

------------------------------------------------------------------------------
-- Layer 6: facts (05_sessions.sql, W8)
------------------------------------------------------------------------------

-- Sessions are computed over plays AND skips together: a new session starts
-- when started_at_utc - MAX(previous ended_at_utc) > 20 min (running maximum,
-- not LAG). Last.fm-only rows use started_at + duration_ms as their end.
CREATE OR REPLACE TABLE sessions (
    session_id        BIGINT PRIMARY KEY,
    started_at_utc    TIMESTAMP NOT NULL,
    ended_at_utc      TIMESTAMP NOT NULL,
    started_at_local  TIMESTAMP NOT NULL,
    tz                VARCHAR NOT NULL,
    n_plays           INTEGER NOT NULL,
    n_skips           INTEGER NOT NULL,
    listen_ms         BIGINT NOT NULL,        -- sum of ms_played (imputed for lastfm rows)
    platform_family   VARCHAR,                -- most common, NULL if lastfm-only
    sources           VARCHAR NOT NULL        -- e.g. 'both', 'lastfm', 'mixed'
);

-- The fact table: one row per real listen (>= 30 s, or any Last.fm scrobble).
CREATE OR REPLACE TABLE plays (
    play_id           BIGINT PRIMARY KEY,     -- = events.event_id
    started_at_utc    TIMESTAMP NOT NULL,
    ended_at_utc      TIMESTAMP NOT NULL,
    started_at_local  TIMESTAMP NOT NULL,
    tz                VARCHAR NOT NULL,       -- IANA zone
    country           VARCHAR,                -- after ZZ imputation; NULL = unknown, treated as US
    country_imputed   BOOLEAN NOT NULL,
    track_id          VARCHAR NOT NULL,
    artist_id         BIGINT NOT NULL,        -- primary artist
    album_id          BIGINT,
    session_id        BIGINT NOT NULL,
    session_index     INTEGER NOT NULL,       -- 1 = session opener (counts skips too)
    new_session_10    BOOLEAN NOT NULL,       -- sensitivity flags: would a 10/30 min gap
    new_session_30    BOOLEAN NOT NULL,       -- threshold start a session here?
    ms_played         BIGINT,                 -- NULL for lastfm-only
    ms_imputed        BIGINT NOT NULL,        -- ms_played, or duration_ms * median completion (>=30 s Spotify plays)
    completion_ratio  DOUBLE,                 -- ms_played / duration_ms, NULL if unknown or longform
    source            VARCHAR NOT NULL,       -- both|spotify|lastfm
    match_pass        TINYINT,
    match_gap_sec     DOUBLE,
    platform_family   VARCHAR,
    shuffle           BOOLEAN,
    offline           BOOLEAN,
    incognito         BOOLEAN,
    reason_start      VARCHAR,
    reason_end        VARCHAR,
    skipped           BOOLEAN
);

-- Spotify events under 30 s with no matching scrobble. Same columns as plays.
CREATE OR REPLACE TABLE skips AS SELECT * FROM plays WHERE false;

------------------------------------------------------------------------------
-- Layer 7: genre (06_genre.py, W9)
------------------------------------------------------------------------------

-- Hand-curated mapping, loaded from data/genre_map.csv.
CREATE OR REPLACE TABLE genre_map (
    tag           VARCHAR PRIMARY KEY,        -- lower-cased Last.fm / Spotify / MB tag
    style         VARCHAR,                    -- NULL when is_genre = false
    parent_genre  VARCHAR,
    is_genre      BOOLEAN NOT NULL,           -- false for 'seen live', 'favorites', years
    is_umbrella   BOOLEAN NOT NULL            -- true for broad parent/scene catch-alls (electronic, edm, dance, indie, alternative, rap, style == parent_genre)
);

-- Weighted coalesce of track (1.0), album (0.7) and artist (0.5) tags after
-- per-entity normalisation. weight sums to 1 per track_id.
CREATE OR REPLACE TABLE track_genre (
    track_id      VARCHAR NOT NULL,
    parent_genre  VARCHAR NOT NULL,
    style         VARCHAR NOT NULL,           -- = parent_genre when no finer style is known
    weight        DOUBLE NOT NULL,
    level         VARCHAR NOT NULL,           -- track|album|artist: best level that contributed
    PRIMARY KEY (track_id, parent_genre, style)
);
