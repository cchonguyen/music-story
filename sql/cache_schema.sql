-- cache_schema.sql: SQLite HTTP response cache for 03_enrich.py (W3).
-- Lives at $CACHE_DIR/http_cache.sqlite, outside the repo, shared by every
-- worktree. A row is written for every response, including 404s, so a rerun
-- never refetches. Only 429/5xx responses are left unwritten and retried.

CREATE TABLE IF NOT EXISTS http_cache (
    api          TEXT    NOT NULL,   -- spotify|musicbrainz|lastfm|deezer|discogs
    endpoint     TEXT    NOT NULL,   -- e.g. 'tracks', 'isrc', 'track.getTopTags'
    key          TEXT    NOT NULL,   -- the lookup key (URI id, ISRC, MBID, 'artist::title')
    status       INTEGER NOT NULL,
    body         TEXT,               -- raw JSON response
    fetched_at   TEXT    NOT NULL,   -- ISO 8601 UTC
    PRIMARY KEY (api, endpoint, key)
);

-- Work queue so an interrupted run resumes in priority order.
CREATE TABLE IF NOT EXISTS fetch_queue (
    api          TEXT    NOT NULL,
    endpoint     TEXT    NOT NULL,
    key          TEXT    NOT NULL,
    priority     INTEGER NOT NULL,   -- lower first; play-count rank
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT,
    PRIMARY KEY (api, endpoint, key)
);
CREATE INDEX IF NOT EXISTS fetch_queue_order ON fetch_queue (api, priority);

-- Long rate-limit lockouts per api: Retry-After over 10 min, a QUOTA_EXCEEDED body, or our own
-- daily budget running out. Reruns send nothing until then, because asking again can extend
-- the lockout. Caches made before `reason` existed get it from Cache.__init__.
CREATE TABLE IF NOT EXISTS api_pause (
    api        TEXT PRIMARY KEY,
    until_utc  TEXT NOT NULL,     -- ISO 8601 UTC
    reason     TEXT               -- e.g. 'QUOTA_EXCEEDED', 'Retry-After', 'budget'
);

-- One row per request actually sent to an api with a daily budget (Spotify), for the rolling
-- 24 h count. Rows older than two days are pruned on insert.
CREATE TABLE IF NOT EXISTS request_log (
    api     TEXT NOT NULL,
    at_utc  TEXT NOT NULL         -- ISO 8601 UTC
);
CREATE INDEX IF NOT EXISTS request_log_api_at ON request_log (api, at_utc);

-- Highest queue priority an api may take (a play-count floor). Rows past it stay queued but
-- are not picked, so moving the floor later needs no reseed. No row = no limit.
CREATE TABLE IF NOT EXISTS api_limit (
    api           TEXT PRIMARY KEY,
    max_priority  INTEGER NOT NULL,
    note          TEXT            -- how the cap was chosen, e.g. 'min_plays=3'
);
