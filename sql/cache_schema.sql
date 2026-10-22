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
