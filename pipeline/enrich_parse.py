"""Parse the HTTP cache into the enr_* tables (build step 03, no network)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import duckdb

from pipeline.enrich_cache import Cache
from pipeline.enrich_clients import deezer_hit


def _ts(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=None)


def _obj(body: str | None) -> dict | None:
    try:
        data = json.loads(body) if body else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _year(v: str | None) -> int | None:
    return _int(v[:4]) if v else None


def _insert(con: duckdb.DuckDBPyConnection, table: str, rows: list[tuple]) -> None:
    if rows:
        marks = ",".join("?" * len(rows[0]))
        con.executemany(f"INSERT OR REPLACE INTO {table} VALUES ({marks})", rows)


# ---- Spotify ------------------------------------------------------------------
def _spotify_tracks(cache: Cache) -> list[tuple]:
    out = []
    for key, status, body, at in cache.rows("spotify", "tracks"):
        d = _obj(body) if status == 200 else None
        uri = f"spotify:track:{key}"
        if not d:
            out.append((uri, None, None, None, None, None, None, None, None, None, None, status, _ts(at)))
            continue
        album = d.get("album") or {}
        artists = [{"id": a.get("id"), "name": a.get("name")} for a in d.get("artists") or []]
        out.append((uri, (d.get("external_ids") or {}).get("isrc"), d.get("name"), d.get("duration_ms"),
                    d.get("explicit"), album.get("id"), album.get("name"), album.get("album_type"),
                    album.get("release_date"), album.get("release_date_precision"), artists, status,
                    _ts(at)))
    return out


def _spotify_artists(cache: Cache) -> list[tuple]:
    out = []
    for key, status, body, at in cache.rows("spotify", "artists"):
        d = _obj(body) if status == 200 else None
        out.append((key, d.get("name") if d else None, (d.get("genres") or []) if d else None, status,
                    _ts(at)))
    return out


# ---- MusicBrainz --------------------------------------------------------------
def _credits(rec: dict) -> list[dict]:
    return [
        {"mbid": (c.get("artist") or {}).get("id"),
         "name": c.get("name") or (c.get("artist") or {}).get("name"),
         "joinphrase": c.get("joinphrase")}
        for c in rec.get("artist-credit") or []
    ]


def _recording_row(kind: str, key: str, rec: dict, score: int | None, first: str | None,
                   isrcs: list[str], status: int, at: str) -> tuple:
    return (kind, key, rec.get("id"), rec.get("title"), rec.get("length"), isrcs, first or None,
            _credits(rec), [g["name"] for g in rec.get("genres") or [] if g.get("name")], score, status,
            _ts(at))


def _mb_recordings(cache: Cache) -> list[tuple]:
    out = []
    for kind, endpoint in (("isrc", "isrc"), ("mbid", "recording"), ("search", "search")):
        for key, status, body, at in cache.rows("musicbrainz", endpoint):
            d = _obj(body) if status == 200 else None
            recs = []
            if d:
                recs = d.get("recordings", []) if endpoint != "recording" else [d]
            recs = [r for r in recs if isinstance(r, dict)]
            if not recs:
                out.append((kind, key, None, None, None, None, None, None, None, None, status, _ts(at)))
                continue
            if kind == "isrc":
                # Several recordings can share an ISRC: keep the earliest first release.
                rec = min(recs, key=lambda r: r.get("first-release-date") or "9999")
                first = min((r["first-release-date"] for r in recs if r.get("first-release-date")),
                            default=None)
                isrcs = rec.get("isrcs") or [key]
                out.append(_recording_row(kind, key, rec, None, first, isrcs, status, at))
            elif kind == "mbid":
                out.append(_recording_row(kind, key, d, None, d.get("first-release-date"),
                                          d.get("isrcs") or [], status, at))
            else:
                rec = max(recs, key=lambda r: _int(r.get("score")) or 0)
                out.append(_recording_row(kind, key, rec, _int(rec.get("score")),
                                          rec.get("first-release-date"), rec.get("isrcs") or [],
                                          status, at))
    return out


def _mb_artists(cache: Cache) -> list[tuple]:
    out = []
    for key, status, body, at in cache.rows("musicbrainz", "artist"):
        d = _obj(body) if status == 200 else None
        if not d:
            out.append((key, None, None, None, None, None, None, status, _ts(at)))
            continue
        span = d.get("life-span") or {}
        out.append((key, d.get("name"), d.get("type"), d.get("country"), _year(span.get("begin")),
                    _year(span.get("end")), [g["name"] for g in d.get("genres") or [] if g.get("name")],
                    status, _ts(at)))
    return out


# ---- Last.fm ------------------------------------------------------------------
_TAG_ENDPOINTS = {"track.getTopTags": "track", "artist.getTopTags": "artist", "album.getTopTags": "album"}


def _lastfm_tags(cache: Cache) -> list[tuple]:
    out = []
    for endpoint, entity in _TAG_ENDPOINTS.items():
        for key, status, body, at in cache.rows("lastfm", endpoint):
            d = _obj(body) if status == 200 else None
            tags = ((d or {}).get("toptags") or {}).get("tag") or []
            if isinstance(tags, dict):  # one tag arrives as a bare object
                tags = [tags]
            best: dict[str, int] = {}
            for t in tags:
                name = (t.get("name") or "").strip().lower()
                if name:
                    best[name] = max(best.get(name, 0), _int(t.get("count")) or 0)
            out.extend((entity, key, name, count, _ts(at)) for name, count in best.items())
    return out


def _lastfm_info(cache: Cache) -> list[tuple]:
    out = []
    for endpoint, entity in (("artist.getInfo", "artist"), ("track.getInfo", "track")):
        for key, status, body, at in cache.rows("lastfm", endpoint):
            d = _obj(body) if status == 200 else None
            if d and d.get("error") == 6:
                status = 404
            node = (d or {}).get(entity)
            if not isinstance(node, dict):
                out.append((entity, key, None, None, None, None, status, _ts(at)))
                continue
            stats = node.get("stats") or node
            duration = _int(node.get("duration")) if entity == "track" else None
            out.append((entity, key, node.get("mbid") or None, _int(stats.get("listeners")),
                        _int(stats.get("playcount")), duration or None, status, _ts(at)))
    return out


# ---- Deezer -------------------------------------------------------------------
def _deezer_body(status: int, body: str | None) -> tuple[int, dict | None]:
    d = _obj(body) if status == 200 else None
    if d and d.get("error"):
        return 404, None
    return status, d


def _deezer_row(key: str, status: int, d: dict | None, at: str) -> tuple:
    if not d:
        return (key, None, None, None, None, None, status, _ts(at))
    dur = _int(d.get("duration"))
    bpm = d.get("bpm")
    return (key, d.get("id"), bpm if bpm else None, d.get("gain"), dur * 1000 if dur else None,
            d.get("release_date"), status, _ts(at))


def _deezer(cache: Cache, by_id: dict[str, tuple[int, dict | None, str]]) -> list[tuple]:
    """enr_deezer_track by ISRC: lookups by ISRC, plus tracks reached through search."""
    out = []
    for key, status, body, at in cache.rows("deezer", "track"):
        status, d = _deezer_body(status, body)
        out.append(_deezer_row(key, status, d, at))
    seen = {r[0] for r in out}
    for status, d, at in by_id.values():
        if d and d.get("isrc") and d["isrc"] not in seen:
            seen.add(d["isrc"])
            out.append(_deezer_row(d["isrc"], status, d, at))
    return out


def _deezer_ids(cache: Cache) -> dict[str, tuple[int, dict | None, str]]:
    out = {}
    for key, status, body, at in cache.rows("deezer", "id"):
        status, d = _deezer_body(status, body)
        out[key] = (status, d, at)
    return out


def _deezer_matches(cache: Cache, by_id: dict[str, tuple[int, dict | None, str]]) -> list[tuple]:
    out = []
    for key, status, body, at in cache.rows("deezer", "search"):
        status, d = _deezer_body(status, body)
        hit = deezer_hit(key, d) if d else None
        if not hit:
            out.append((key, None, None, None, None, None, None, 404 if status == 200 else status, _ts(at)))
            continue
        id_status, t, id_at = by_id.get(str(hit["id"]), (status, None, at))
        album = (t or hit).get("album") or {}
        dur = _int((t or hit).get("duration"))
        out.append((key, _int(hit["id"]), (t or {}).get("isrc"), _int(album.get("id")), album.get("title"),
                    (t or {}).get("release_date"), dur * 1000 if dur else None, id_status, _ts(id_at)))
    return out


def _gemini_artist_genres(cache: Cache) -> list[tuple]:
    out = []
    # Reads every endpoint matching 'artist_genre:*'
    with cache.lock:
        cur = cache.db.execute(
            "SELECT endpoint, key, status, body, fetched_at FROM http_cache WHERE api = 'gemini' AND endpoint LIKE 'artist_genre:%'"
        ).fetchall()
    for endpoint, key, status, body, at in cur:
        if status != 200 or not body:
            continue
        parts = endpoint.split(":")
        model_id = parts[1] if len(parts) > 1 else "unknown"
        prompt_ver = parts[2] if len(parts) > 2 else "v1"
        d = _obj(body)
        if not d or not isinstance(d.get("styles"), list):
            continue
        genre_keys = []
        weights = []
        for s in d["styles"]:
            if isinstance(s, dict) and s.get("parent") and s.get("style"):
                genre_keys.append(f"{s['parent']}::{s['style']}")
                weights.append(float(s.get("weight", 1.0)))
        reason = d.get("reasoning")
        out.append((key, model_id, prompt_ver, genre_keys, weights, reason, _ts(at)))
    return out


def _discogs_artist_styles(cache: Cache) -> list[tuple]:
    out = []
    for key, status, body, at in cache.rows("discogs", "artist_styles"):
        if status != 200 or not body:
            continue
        d = _obj(body)
        if not d:
            continue
        d_id = _int(d.get("discogs_artist_id"))
        if not d_id:
            continue
        genres = [str(g).strip().lower() for g in d.get("genres") or [] if g]
        styles = [str(s).strip().lower() for s in d.get("styles") or [] if s]
        cnt = _int(d.get("master_count")) or 0
        out.append((key, d_id, genres, styles, cnt, _ts(at)))
    return out


def parse_cache(con: duckdb.DuckDBPyConnection, cache: Cache) -> None:
    for table in ("enr_spotify_track", "enr_spotify_artist", "enr_mb_recording", "enr_mb_artist",
                  "enr_lastfm_tags", "enr_lastfm_info", "enr_deezer_track", "enr_deezer_match",
                  "enr_artist_genre_llm", "enr_discogs_artist"):
        con.execute(f"DELETE FROM {table}")
    _insert(con, "enr_spotify_track", _spotify_tracks(cache))
    _insert(con, "enr_spotify_artist", _spotify_artists(cache))
    _insert(con, "enr_mb_recording", _mb_recordings(cache))
    _insert(con, "enr_mb_artist", _mb_artists(cache))
    _insert(con, "enr_lastfm_tags", _lastfm_tags(cache))
    _insert(con, "enr_lastfm_info", _lastfm_info(cache))
    by_id = _deezer_ids(cache)
    _insert(con, "enr_deezer_track", _deezer(cache, by_id))
    _insert(con, "enr_deezer_match", _deezer_matches(cache, by_id))
    _insert(con, "enr_artist_genre_llm", _gemini_artist_genres(cache))
    _insert(con, "enr_discogs_artist", _discogs_artist_styles(cache))


def local_durations(con: duckdb.DuckDBPyConnection) -> None:
    """MAX(ms_played) over completed, unskipped plays. A NULL skipped flag (old exports) is not a skip."""
    con.execute("DELETE FROM enr_local_duration")
    con.execute(
        """INSERT INTO enr_local_duration
           SELECT track_uri, MAX(ms_played), COUNT(*) FROM stg_spotify
           WHERE reason_end = 'trackdone' AND NOT COALESCE(skipped, false)
           GROUP BY track_uri"""
    )
