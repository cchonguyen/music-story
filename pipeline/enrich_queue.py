"""Seed the fetch queue from `events`. Priority = rank by play count (1 = most played).

Only root items are seeded here. Follow-ups that depend on a response (Spotify
artists, ISRC lookups, Deezer, MusicBrainz artists from credits) are queued by
pipeline.enrich_clients.cascade in the same transaction that stores the response.
"""

from __future__ import annotations

from collections import Counter

import duckdb

from pipeline.enrich_cache import Cache, QueueItem
from pipeline.normalize import normalize_album

TOP_LASTFM_TRACKS = 2000
TOP_LASTFM_ALBUMS = 1000

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
    ("lastfm", "album.getTopTags"): None,  # keys need normalize_album, see _albums
    ("lastfm", "track.getInfo"): f"""
        SELECT {TRACK_KEY} FROM events WHERE {LFM_ONLY} GROUP BY 1 ORDER BY count(*) DESC, 1""",
}


def seed_queue(con: duckdb.DuckDBPyConnection, cache: Cache, apis: set[str]) -> dict[tuple[str, str], int]:
    """Insert root items for the chosen apis; returns how many were offered per endpoint."""
    offered: dict[tuple[str, str], int] = {}
    for (api, endpoint), sql in _SQL.items():
        if api not in apis:
            continue
        if sql is None:
            keys = list(_albums(con))[:TOP_LASTFM_ALBUMS]
        else:
            keys = [r[0] for r in con.execute(sql).fetchall() if r[0]]
        items: list[QueueItem] = [(api, endpoint, k, rank) for rank, k in enumerate(keys, 1)]
        cache.enqueue(items)
        offered[(api, endpoint)] = len(items)
    return offered


def spotify_cap(con: duckdb.DuckDBPyConnection, min_plays: int) -> int:
    """Highest Spotify track priority with at least `min_plays` plays. Ranks follow play count, so
    every URI within the cap has min_plays or more; follow-ups inherit their track's rank."""
    return con.execute("""SELECT count(*) FROM (
        SELECT split_part(track_uri, ':', 3) FROM events WHERE track_uri LIKE 'spotify:track:%'
        GROUP BY 1 HAVING count(*) >= ?)""", [min_plays]).fetchone()[0]


def load_names(con: duckdb.DuckDBPyConnection) -> dict:
    """Most common raw spellings per norm key, used to build Last.fm / MusicBrainz requests."""
    track = {
        k: (a, t) for k, a, t in con.execute(
            f"SELECT {TRACK_KEY}, mode(artist_raw), mode(track_raw) FROM events GROUP BY 1"
        ).fetchall()
    }
    artist = dict(con.execute("SELECT artist_norm, mode(artist_raw) FROM events GROUP BY 1").fetchall())
    album = _albums(con)
    return {"track": track, "artist": artist, "album": album}


def _albums(con: duckdb.DuckDBPyConnection) -> dict[str, tuple[str, str]]:
    """'artist_norm::album_norm' -> most common (artist_raw, album_raw), most played key first."""
    plays: Counter[str] = Counter()
    artist_spell: dict[str, Counter[str]] = {}
    album_spell: dict[str, Counter[str]] = {}
    rows = con.execute("""SELECT artist_norm, album_raw, artist_raw, count(*) FROM events
                          WHERE album_raw IS NOT NULL GROUP BY 1, 2, 3""").fetchall()
    for artist_norm, album_raw, artist_raw, n in rows:
        album_norm = normalize_album(album_raw)
        if not album_norm or not artist_norm:
            continue
        k = f"{artist_norm}::{album_norm}"
        plays[k] += n
        artist_spell.setdefault(k, Counter())[artist_raw] += n
        album_spell.setdefault(k, Counter())[album_raw] += n
    order = sorted(plays, key=lambda k: (-plays[k], k))
    return {k: (_top(artist_spell[k]), _top(album_spell[k])) for k in order}


def _top(c: Counter[str]) -> str:
    return min(c, key=lambda v: (-c[v], v))
