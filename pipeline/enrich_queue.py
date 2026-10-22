"""Seed the fetch queue from `events`. Priority = rank by play count (1 = most played).

Only root items are seeded here. Follow-ups that depend on a response (Spotify
artists, ISRC lookups, Deezer, MusicBrainz artists from credits) are queued by
pipeline.enrich_clients.cascade in the same transaction that stores the response.
"""

from __future__ import annotations

import duckdb

from pipeline.enrich_cache import Cache, QueueItem

TOP_LASTFM_TRACKS = 2000
TOP_LASTFM_ALBUMS = 1000

# Album key: lower-cased, whitespace-collapsed raw album name. Reconcile with
# normalize.py when W2 lands (see W3 report).
ALBUM_KEY = r"lower(trim(regexp_replace(album_raw, '\s+', ' ', 'g')))"
TRACK_KEY = "artist_norm || '::' || full_norm"
LFM_ONLY = "track_uri IS NULL"
NO_MBID = "(track_mbid IS NULL OR track_mbid = '')"

_SQL = {
    ("spotify", "tracks"): """
        SELECT split_part(track_uri, ':', 3) AS k FROM events
        WHERE track_uri LIKE 'spotify:track:%' GROUP BY 1 ORDER BY count(*) DESC, 1""",
    ("musicbrainz", "recording"): f"""
        SELECT track_mbid FROM events WHERE {LFM_ONLY} AND NOT {NO_MBID}
        GROUP BY 1 ORDER BY count(*) DESC, 1""",
    ("musicbrainz", "search"): f"""
        SELECT {TRACK_KEY} FROM events WHERE {LFM_ONLY} AND {NO_MBID}
        GROUP BY 1 ORDER BY count(*) DESC, 1""",
    ("musicbrainz", "artist"): """
        SELECT artist_mbid FROM events WHERE artist_mbid IS NOT NULL AND artist_mbid <> ''
        GROUP BY 1 ORDER BY count(*) DESC, 1""",
    ("lastfm", "track.getTopTags"): f"""
        SELECT {TRACK_KEY} FROM events GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT {TOP_LASTFM_TRACKS}""",
    ("lastfm", "artist.getTopTags"): "SELECT artist_norm FROM events GROUP BY 1 ORDER BY count(*) DESC, 1",
    ("lastfm", "artist.getInfo"): "SELECT artist_norm FROM events GROUP BY 1 ORDER BY count(*) DESC, 1",
    ("lastfm", "album.getTopTags"): f"""
        SELECT artist_norm || '::' || {ALBUM_KEY} FROM events
        WHERE album_raw IS NOT NULL AND trim(album_raw) <> ''
        GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT {TOP_LASTFM_ALBUMS}""",
    ("lastfm", "track.getInfo"): f"""
        SELECT {TRACK_KEY} FROM events WHERE {LFM_ONLY} GROUP BY 1 ORDER BY count(*) DESC, 1""",
}


def seed_queue(con: duckdb.DuckDBPyConnection, cache: Cache, apis: set[str]) -> dict[tuple[str, str], int]:
    """Insert root items for the chosen apis; returns how many were offered per endpoint."""
    offered: dict[tuple[str, str], int] = {}
    for (api, endpoint), sql in _SQL.items():
        if api not in apis:
            continue
        keys = [r[0] for r in con.execute(sql).fetchall() if r[0]]
        items: list[QueueItem] = [(api, endpoint, k, rank) for rank, k in enumerate(keys, 1)]
        cache.enqueue(items)
        offered[(api, endpoint)] = len(items)
    return offered


def load_names(con: duckdb.DuckDBPyConnection) -> dict:
    """Most common raw spellings per norm key, used to build Last.fm / MusicBrainz requests."""
    track = {
        k: (a, t) for k, a, t in con.execute(
            f"SELECT {TRACK_KEY}, mode(artist_raw), mode(track_raw) FROM events GROUP BY 1"
        ).fetchall()
    }
    artist = dict(con.execute("SELECT artist_norm, mode(artist_raw) FROM events GROUP BY 1").fetchall())
    album = {
        k: (a, al) for k, a, al in con.execute(
            f"""SELECT artist_norm || '::' || {ALBUM_KEY}, mode(artist_raw), mode(album_raw) FROM events
                WHERE album_raw IS NOT NULL AND trim(album_raw) <> '' GROUP BY 1"""
        ).fetchall()
    }
    return {"track": track, "artist": artist, "album": album}
