"""Read-only audit of what the Spotify queue would still add. Prints counts only.

    uv run python scripts/enrich_audit.py [--cover 0.80]

Needs build/music.duckdb built through step 04 and the HTTP cache. Opens both read-only.
"""

import argparse
import json
import sqlite3
from collections import Counter

import duckdb

from pipeline import config
from pipeline.enrich_clients import deezer_hit
from pipeline.normalize import normalize_artist, normalize_title


def deezer_search(cache: sqlite3.Connection) -> None:
    out: Counter[str] = Counter()
    for key, status, body in cache.execute(
            "SELECT key, status, body FROM http_cache WHERE api='deezer' AND endpoint='search'"):
        try:
            d = json.loads(body) if body else None
        except ValueError:
            d = None
        if status != 200 or not isinstance(d, dict):
            out[f"http {status} / unparsable"] += 1
        elif d.get("error"):
            out[f"error code {(d['error'] or {}).get('code')}"] += 1
        elif not d.get("data"):
            out["no results"] += 1
        elif deezer_hit(key, d):
            out["exact hit"] += 1
        else:
            artist, _, title = key.partition("::")
            hits = [h for h in d["data"] if isinstance(h, dict)]
            a = any(normalize_artist((h.get("artist") or {}).get("name")) == artist for h in hits)
            t = any(normalize_title(h.get("title"))[0] == title for h in hits)
            out["results, artist+title both match other hits" if a and t else
                "results, artist matches only" if a else
                "results, title matches only" if t else "results, neither matches"] += 1
    ids = cache.execute("SELECT count(*) FROM http_cache WHERE api='deezer' AND endpoint='id'").fetchone()[0]
    print("deezer.search outcomes:")
    for k, n in out.most_common():
        print(f"  {k:48} {n:7}")
    print(f"  deezer.id responses stored                       {ids:7}")


def mb_search(cache: sqlite3.Connection) -> None:
    out: Counter[str] = Counter()
    for status, body in cache.execute(
            "SELECT status, body FROM http_cache WHERE api='musicbrainz' AND endpoint='search'"):
        try:
            recs = (json.loads(body) or {}).get("recordings") or [] if status == 200 and body else []
        except ValueError:
            recs = []
        top = recs[0] if recs else None
        if not top:
            out["no results"] += 1
        elif (top.get("score") or 0) < 90:
            out["top score < 90"] += 1
        elif top.get("isrcs"):
            out["score >= 90 with ISRC"] += 1
        else:
            out["score >= 90, no ISRC"] += 1
    print("musicbrainz.search outcomes (top recording):")
    for k, n in out.most_common():
        print(f"  {k:48} {n:7}")


TRACK_COLS = ["isrc", "album_id", "duration_ms", "recording_year", "lastfm_listeners"]


def overlap(cache: sqlite3.Connection, cover: float) -> None:
    con = duckdb.connect()
    con.execute(f"ATTACH '{config.MUSIC_DB}' AS m (READ_ONLY)")
    con.execute("USE m")
    from pipeline.enrich_queue import spotify_cap_cover
    cap, share = spotify_cap_cover(con, cover)
    con.execute("USE memory")
    con.execute("CREATE TEMP TABLE q (k VARCHAR, pr INTEGER, state VARCHAR)")
    done = {r[0] for r in cache.execute("SELECT key FROM http_cache WHERE api='spotify' AND endpoint='tracks'")}
    rows = [(k, p, "fetched" if k in done else ("queued, under cap" if p <= cap else "queued, past cap"))
            for k, p in cache.execute("SELECT key, priority FROM fetch_queue WHERE api='spotify' "
                                      "AND endpoint='tracks'")]
    rows += [(k, 0, "fetched") for k in done - {r[0] for r in rows}]
    con.executemany("INSERT INTO q VALUES (?, ?, ?)", rows)
    print(f"\nspotify cap for cover {cover}: priority <= {cap} ({share:.2%} of Spotify plays)")
    cols = ", ".join(f"sum(n) FILTER (WHERE t.{c} IS NULL) AS {c}" for c in TRACK_COLS)
    res = con.execute(f"""
        WITH u AS (SELECT track_uri, split_part(track_uri, ':', 3) AS k, count(*) AS n FROM m.events
                   WHERE track_uri LIKE 'spotify:track:%' GROUP BY 1, 2)
        SELECT q.state, count(*) AS uris, sum(n) AS plays,
               sum(n) FILTER (WHERE t.isrc IS NULL AND t.album_id IS NULL) AS blind,
               sum(n) FILTER (WHERE a.spotify_artist_id IS NULL) AS no_sp_artist,
               sum(n) FILTER (WHERE al.album_type IS NULL) AS no_album_type, {cols}
        FROM u JOIN q USING (k)
        JOIN m.track_uri_map USING (track_uri) JOIN m.dim_track t USING (track_id)
        LEFT JOIN m.dim_artist a ON a.artist_id = t.primary_artist_id
        LEFT JOIN m.dim_album al ON al.album_id = t.album_id
        GROUP BY 1 ORDER BY 1""")
    names = [d[0] for d in res.description]
    print("Spotify-URI plays by queue state; column counts are plays whose value is NULL:")
    for r in res.fetchall():
        d = dict(zip(names, r))
        print(f"  {d['state']}: {d['uris']} URIs, {d['plays']} plays")
        for c in names[3:]:
            print(f"    {c:18} {d[c] or 0:7}  ({(d[c] or 0) / d['plays']:.1%})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cover", type=float, default=0.80)
    args = ap.parse_args()
    cache = sqlite3.connect(f"file:{config.CACHE_DIR / 'http_cache.sqlite'}?mode=ro", uri=True)
    deezer_search(cache)
    mb_search(cache)
    overlap(cache, args.cover)


if __name__ == "__main__":
    main()
