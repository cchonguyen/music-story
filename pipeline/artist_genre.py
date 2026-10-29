"""Artist genres for Concert Tracker (concert.charliechonguyen.com).

    uv run python -m pipeline.artist_genre export [--out build/artist_genres.json]

Reads MUSIC_DB after build_pipeline (step 06 loads genre_map) and writes one JSON file:
every artist with at least one genre, plus the genre map, so Concert Tracker can map
MusicBrainz tags for acts you saw live but never streamed the same way. The file stays on
your machine (build/ is ignored); you upload it in Concert Tracker's Table tab.

Artist level only, from the same inputs and rules as track_genre's artist level: Last.fm
artist tags (their count), Spotify and MusicBrainz artist genres (100 each), kept when
genre_map says is_genre, weight = share of the artist's total, styles under MIN_SHARE
dropped and the rest renormalised to sum to 1.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from pipeline import config
from pipeline.genre import MIN_SHARE

FORMAT = "music-story/artist-genres"
VERSION = 1
DEFAULT_OUT = config.REPO_ROOT / "build" / "artist_genres.json"

ARTIST_SQL = """
WITH tagged AS (
    SELECT d.artist_id, 'lastfm' AS input, l.tag, l.count::DOUBLE AS cnt
    FROM dim_artist d JOIN enr_lastfm_tags l ON l.entity_type = 'artist' AND l.entity_key = d.artist_norm
    UNION ALL
    SELECT d.artist_id, 'spotify', lower(trim(g.tag)), 100.0
    FROM dim_artist d JOIN enr_spotify_artist s ON s.spotify_artist_id = d.spotify_artist_id, unnest(s.genres) g(tag)
    UNION ALL
    SELECT d.artist_id, 'musicbrainz', lower(trim(g.tag)), 100.0
    FROM dim_artist d JOIN enr_mb_artist m ON m.artist_mbid = d.artist_mbid, unnest(m.genres) g(tag)
),
styled AS (
    SELECT t.artist_id, m.parent_genre, m.style, sum(t.cnt) AS cnt, list(DISTINCT t.input) AS inputs
    FROM tagged t JOIN genre_map m ON m.tag = t.tag AND m.is_genre
    GROUP BY ALL
),
kept AS (
    SELECT * FROM styled
    QUALIFY cnt >= __MIN__ * sum(cnt) OVER (PARTITION BY artist_id)
)
SELECT d.name, d.artist_norm, d.artist_mbid, k.parent_genre, k.style,
       k.cnt / sum(k.cnt) OVER (PARTITION BY k.artist_id) AS weight, k.inputs
FROM kept k JOIN dim_artist d USING (artist_id)
ORDER BY d.artist_norm, weight DESC, k.style
""".replace("__MIN__", str(MIN_SHARE))


def artist_genres(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """One entry per artist with a genre: name, artist_norm, mbid, genres (weight sums to 1), inputs."""
    out: dict[str, dict] = {}
    for name, norm, mbid, parent, style, weight, inputs in con.execute(ARTIST_SQL).fetchall():
        a = out.setdefault(norm, {"name": name, "artist_norm": norm, "mbid": mbid, "genres": [], "inputs": set()})
        a["genres"].append({"parent": parent, "style": style, "weight": round(weight, 4)})
        a["inputs"].update(inputs)
    return [{**a, "inputs": sorted(a["inputs"])} for a in out.values()]


def genre_map(con: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = con.execute("SELECT tag, style, parent_genre FROM genre_map WHERE is_genre ORDER BY tag").fetchall()
    return [{"tag": t, "style": s, "parent": p} for t, s, p in rows]


def export(con: duckdb.DuckDBPyConnection, out: Path) -> dict:
    doc = {
        "format": FORMAT,
        "version": VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "genre_map": genre_map(con),
        "artists": artist_genres(con),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    return doc


def main() -> None:
    ap = argparse.ArgumentParser(prog="pipeline.artist_genre")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="write artist genres for Concert Tracker")
    e.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    con = duckdb.connect(str(config.MUSIC_DB), read_only=True)
    doc = export(con, args.out)
    print(f"{len(doc['artists'])} artists, {len(doc['genre_map'])} genre tags -> {args.out}")


if __name__ == "__main__":
    main()
