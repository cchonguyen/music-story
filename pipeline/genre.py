"""Step 06 (W9): genre taxonomy. Loads data/genre_map.csv and builds track_genre.

    uv run python -m pipeline.genre unmapped [--top N]   # unmapped tags by plays, for curation
"""

from __future__ import annotations

import argparse

import duckdb

from pipeline import config

GENRE_MAP_CSV = config.REPO_ROOT / "data" / "genre_map.csv"
MIN_SHARE = 0.15

LOAD_SQL = f"""
DELETE FROM genre_map;
INSERT INTO genre_map
SELECT lower(trim(tag)), nullif(trim(style), ''), nullif(trim(parent_genre), ''), lower(trim(is_genre)) = 'true'
FROM read_csv('{GENRE_MAP_CSV}', header = true, all_varchar = true);
INSERT INTO genre_map
SELECT DISTINCT t, NULL, NULL, false FROM (
    SELECT y::VARCHAR AS t FROM range(1900, 2100) r(y)
    UNION ALL SELECT (y // 10 * 10)::VARCHAR || 's' FROM range(1900, 2100, 10) r(y)
    UNION ALL SELECT lpad((y % 100)::VARCHAR, 2, '0') || 's' FROM range(1900, 2100, 10) r(y)
) WHERE t NOT IN (SELECT tag FROM genre_map);
"""

BUILD_SQL = """
DELETE FROM track_genre;
INSERT INTO track_genre
WITH lvl AS (
    -- (track_id, level, tag, count)
    SELECT t.track_id, 'track' AS level, l.tag, l.count::DOUBLE AS cnt
    FROM dim_track t JOIN enr_lastfm_tags l
      ON l.entity_type = 'track' AND l.entity_key = t.artist_norm || '::' || t.full_norm
    UNION ALL
    -- MB recordings reach a track through any ISRC they list (isrc and mbid lookups) or, for
    -- search lookups, through the track's key; each recording counts once per track.
    SELECT track_id, 'track', lower(trim(g.tag)), 100.0
    FROM (
        SELECT DISTINCT t.track_id, r.genres
        FROM dim_track t
        JOIN (SELECT genres, unnest(isrcs) AS isrc FROM enr_mb_recording WHERE http_status = 200) r
          ON r.isrc = t.isrc
        UNION
        SELECT t.track_id, r.genres
        FROM dim_track t JOIN enr_mb_recording r
          ON r.lookup_kind = 'search' AND r.lookup_key = t.artist_norm || '::' || t.full_norm AND r.score >= 90
    ) x, unnest(x.genres) g(tag)
    UNION ALL
    SELECT t.track_id, 'album', l.tag, l.count::DOUBLE
    FROM dim_track t JOIN dim_album a USING (album_id) JOIN dim_artist pa ON pa.artist_id = a.primary_artist_id
    JOIN enr_lastfm_tags l
      ON l.entity_type = 'album' AND l.entity_key = pa.artist_norm || '::' || a.album_norm
    UNION ALL
    SELECT t.track_id, 'artist', l.tag, l.count::DOUBLE
    FROM dim_track t JOIN dim_artist d ON d.artist_id = t.primary_artist_id JOIN enr_lastfm_tags l
      ON l.entity_type = 'artist' AND l.entity_key = d.artist_norm
    UNION ALL
    SELECT t.track_id, 'artist', lower(trim(g.tag)), 100.0
    FROM dim_track t JOIN dim_artist d ON d.artist_id = t.primary_artist_id
    JOIN enr_spotify_artist s ON s.spotify_artist_id = d.spotify_artist_id, unnest(s.genres) g(tag)
    UNION ALL
    SELECT t.track_id, 'artist', lower(trim(g.tag)), 100.0
    FROM dim_track t JOIN dim_artist d ON d.artist_id = t.primary_artist_id
    JOIN enr_mb_artist m ON m.artist_mbid = d.artist_mbid, unnest(m.genres) g(tag)
),
styled AS (
    SELECT l.track_id, l.level, m.parent_genre, m.style, sum(l.cnt) AS cnt
    FROM lvl l JOIN genre_map m ON m.tag = l.tag AND m.is_genre
    GROUP BY ALL
),
norm AS (
    SELECT *, cnt / sum(cnt) OVER (PARTITION BY track_id, level) AS share FROM styled
),
combined AS (
    SELECT track_id, parent_genre, style,
           sum(share * CASE level WHEN 'track' THEN 1.0 WHEN 'album' THEN 0.7 ELSE 0.5 END) AS w,
           min(CASE level WHEN 'track' THEN 1 WHEN 'album' THEN 2 ELSE 3 END) AS lv
    FROM norm GROUP BY ALL
),
kept AS (
    SELECT * FROM combined
    QUALIFY w >= __MIN__ * sum(w) OVER (PARTITION BY track_id)
),
-- level = first of track, album, artist that contributed a kept style
lev AS (
    SELECT track_id, min(lv) AS lv FROM kept GROUP BY 1
)
SELECT k.track_id, k.parent_genre, k.style, k.w / sum(k.w) OVER (PARTITION BY k.track_id),
       CASE e.lv WHEN 1 THEN 'track' WHEN 2 THEN 'album' ELSE 'artist' END
FROM kept k JOIN lev e USING (track_id);
""".replace("__MIN__", str(MIN_SHARE))


def run(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(LOAD_SQL)
    con.execute(BUILD_SQL)


def unmapped(con: duckdb.DuckDBPyConnection, top: int) -> list[tuple[int, str]]:
    """Unmapped tags ranked by plays behind them (track, album and artist level)."""
    return con.execute("""
        WITH tagged AS (
            SELECT t.track_id, l.tag FROM dim_track t JOIN enr_lastfm_tags l
              ON l.entity_type = 'track' AND l.entity_key = t.artist_norm || '::' || t.full_norm
            UNION ALL
            SELECT t.track_id, l.tag FROM dim_track t JOIN dim_artist d ON d.artist_id = t.primary_artist_id
              JOIN enr_lastfm_tags l ON l.entity_type = 'artist' AND l.entity_key = d.artist_norm
            UNION ALL
            SELECT t.track_id, l.tag FROM dim_track t JOIN dim_album a USING (album_id)
              JOIN dim_artist d ON d.artist_id = a.primary_artist_id
              JOIN enr_lastfm_tags l ON l.entity_type = 'album' AND l.entity_key = d.artist_norm || '::' || a.album_norm
            UNION ALL
            SELECT t.track_id, lower(trim(g.tag)) FROM dim_track t JOIN dim_artist d ON d.artist_id = t.primary_artist_id
              JOIN enr_spotify_artist s ON s.spotify_artist_id = d.spotify_artist_id, unnest(s.genres) g(tag)
        ), pc AS (SELECT track_id, count(*) AS n FROM plays GROUP BY 1)
        SELECT sum(pc.n)::BIGINT AS p, tag FROM (SELECT DISTINCT track_id, tag FROM tagged) x
        JOIN pc USING (track_id) WHERE tag NOT IN (SELECT tag FROM genre_map)
        GROUP BY tag ORDER BY p DESC, tag LIMIT ?""", [top]).fetchall()


def main() -> None:
    ap = argparse.ArgumentParser(prog="pipeline.genre")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("unmapped", help="print unmapped tags by plays")
    u.add_argument("--top", type=int, default=50)
    args = ap.parse_args()
    con = duckdb.connect(str(config.MUSIC_DB), read_only=True)
    for plays, tag in unmapped(con, args.top):
        print(f"{plays}\t{tag}")


if __name__ == "__main__":
    main()
