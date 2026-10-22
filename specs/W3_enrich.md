# W3: enrichment clients and the overnight fetch

Tier: Sonnet (maxTurns 30). Deliverable: `pipeline/enrich.py` (+ helpers under `pipeline/enrich_*.py`).

## Read only
`sql/schema.sql` Layer 4, `sql/cache_schema.sql`, `pipeline/config.py`, this spec.

## CLI
- `uv run python -m pipeline.enrich fetch [--api spotify,musicbrainz,lastfm,deezer] [--max-minutes N]`
  builds the queue from MUSIC_DB (needs steps 01-02 done), then works it in priority order. Resumable:
  kill it any time, rerun continues. Prints one progress line per minute, never response bodies.
- `uv run python -m pipeline.enrich status` prints done / queued / failed per api and endpoint.
- `run(con)` (build step 03) parses `http_cache` into the enr_* tables and computes enr_local_duration.
  No network in `run`.

## Cache
SQLite at `$CACHE_DIR/http_cache.sqlite` with `sql/cache_schema.sql`. Store every response including
404. On 429 honour Retry-After; on 5xx back off exponentially, max 5 attempts, then record last_error.
httpx with a single client per api and explicit timeouts.

## Queue and priority (play count = events grouped by the key, most first; no caps)
1. enr_local_duration: MAX(ms_played) per track_uri WHERE reason_end = 'trackdone' AND NOT skipped.
2. Spotify `GET /v1/tracks/{id}` per URI, client-credentials token, about 3 req/s. Batch endpoints are
   gone for Development Mode apps (Feb 2026); popularity is gone too. Keep external_ids.isrc,
   duration_ms, album (id, name, album_type, release_date, precision), artists[]. Then
   `GET /v1/artists/{id}` for primary artists (genres may be empty; store what comes back).
3. MusicBrainz, 1 req/s, User-Agent `music-story/0.1 ( MUSICBRAINZ_CONTACT )`:
   `/ws/2/isrc/{isrc}?inc=artist-credits+releases` for ISRCs (gives first-release-date);
   `/ws/2/recording/{mbid}?inc=isrcs+artist-credits+releases+genres` for Last.fm-only rows with track_mbid;
   `/ws/2/recording?query=recording:"t" AND artist:"a"&limit=5` for Last.fm-only rows without one (keep score);
   `/ws/2/artist/{mbid}?inc=genres` for artist mbids.
4. Last.fm, about 4 req/s, `autocorrect=1`: `track.getTopTags` for the top 2,000 tracks by plays, then
   `artist.getTopTags` and `artist.getInfo` (listeners) for every artist, `album.getTopTags` for the top
   1,000 albums, `track.getInfo` for Last.fm-only tracks (duration). Keys use the norm columns as in
   schema.sql (`artist_norm::full_norm`), the request uses the most common raw spelling.
5. Deezer (optional, no key): `https://api.deezer.com/track/isrc:{ISRC}`, max 50 req / 5 s; bpm 0 -> NULL.

## Done when
Unit tests with `httpx.MockTransport` (no network) cover: cache hit skips the request, 404 is cached,
429 retries after Retry-After, queue order follows play count, `run(con)` fills every enr_* table from a
small canned cache. `uv run pytest` and ruff green. Report the estimated hours per api for the real queue.
