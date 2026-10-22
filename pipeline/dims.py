"""Step 04 (W7): dimensions and track identity. See specs/W7_dims.md.

Reads `events` and `enr_*`; deletes then refills track_uri_map, track_key_map, dim_track,
dim_artist, dim_album and bridge_track_artist. Works on distinct keys (URIs, artist/title keys,
tracks), so it scales with the catalogue, not the event count. Prints counts only.
"""

from __future__ import annotations

import duckdb

from pipeline.normalize import GENERIC_MIX, mix_credit, normalize_album, normalize_artist, normalize_title

TABLES = ["bridge_track_artist", "dim_track", "dim_album", "dim_artist", "track_key_map", "track_uri_map"]

# Normalisation stays in Python (pipeline/normalize.py). Distinct strings are fetched, mapped and
# loaded back as small lookup tables: (sql producing distinct strings, function, table name).
LOOKUPS = {
    "_n_artist": ("""SELECT DISTINCT a.name FROM (SELECT unnest(artists) AS a FROM _sp) WHERE a.name IS NOT NULL
                     UNION SELECT DISTINCT c.name FROM (SELECT unnest(artist_credits) AS c FROM _mb)
                     WHERE c.name IS NOT NULL""", normalize_artist),
    "_n_album": ("SELECT DISTINCT album_name FROM _sp WHERE album_name IS NOT NULL", normalize_album),
    "_n_mix": ("SELECT DISTINCT mix_desc FROM events WHERE mix_desc IS NOT NULL", mix_credit),
    "_n_title": ("SELECT DISTINCT name FROM _sp WHERE name IS NOT NULL", lambda s: normalize_title(s)[0]),
}


def _lookup(con: duckdb.DuckDBPyConnection, table: str) -> None:
    sql, fn = LOOKUPS[table]
    keys = [r[0] for r in con.execute(sql).fetchall()]
    con.execute(f"CREATE OR REPLACE TEMP TABLE {table} AS SELECT unnest(?::VARCHAR[]) AS k, "
                "unnest(?::VARCHAR[]) AS v", [keys, [fn(k) for k in keys]])


# Each statement builds one temp table; order matters.
STEPS = [
    # --- Spotify / MB lookups -------------------------------------------------------------
    """CREATE OR REPLACE TEMP TABLE _sp AS
       SELECT * FROM enr_spotify_track WHERE http_status = 200""",
    """CREATE OR REPLACE TEMP TABLE _mb AS
       SELECT * FROM enr_mb_recording WHERE http_status = 200""",
    # --- 1. per URI: plays, most common mbid, most common key ------------------------------
    """CREATE OR REPLACE TEMP TABLE _uri AS
       SELECT track_uri, count(*) AS n FROM events WHERE track_uri IS NOT NULL GROUP BY 1""",
    """CREATE OR REPLACE TEMP TABLE _uri_mbid AS
       SELECT track_uri, track_mbid FROM (
           SELECT track_uri, track_mbid, count(*) AS n FROM events
           WHERE track_uri IS NOT NULL AND track_mbid IS NOT NULL GROUP BY 1, 2)
       QUALIFY row_number() OVER (PARTITION BY track_uri ORDER BY n DESC, track_mbid) = 1""",
    """CREATE OR REPLACE TEMP TABLE _uri_key AS
       SELECT track_uri, artist_norm || '::' || full_norm AS fkey FROM (
           SELECT track_uri, artist_norm, full_norm, count(*) AS n FROM events
           WHERE track_uri IS NOT NULL GROUP BY 1, 2, 3)
       QUALIFY row_number() OVER (PARTITION BY track_uri ORDER BY n DESC, artist_norm, full_norm) = 1""",
    """CREATE OR REPLACE TEMP TABLE _uri_track AS
       SELECT u.track_uri, u.n,
              coalesce(s.isrc, mb.isrcs[1], k.fkey) AS track_id,
              CASE WHEN s.isrc IS NOT NULL THEN 'isrc' WHEN mb.isrcs[1] IS NOT NULL THEN 'mb_isrc'
                   ELSE 'fallback' END AS kind
       FROM _uri u
       JOIN _uri_key k USING (track_uri)
       LEFT JOIN _sp s USING (track_uri)
       LEFT JOIN _uri_mbid m USING (track_uri)
       LEFT JOIN _mb mb ON mb.lookup_kind = 'mbid' AND mb.lookup_key = m.track_mbid""",
    """INSERT INTO track_uri_map SELECT track_uri, track_id FROM _uri_track""",
    # --- 2. keys: Spotify-backed first, then Last.fm-only fallbacks -------------------------
    """CREATE OR REPLACE TEMP TABLE _sp_key AS
       SELECT artist_norm, full_norm, track_id FROM (
           SELECT e.artist_norm, e.full_norm, m.track_id, count(*) AS n
           FROM events e JOIN track_uri_map m USING (track_uri) GROUP BY 1, 2, 3)
       QUALIFY row_number() OVER (PARTITION BY artist_norm, full_norm ORDER BY n DESC, track_id) = 1""",
    """CREATE OR REPLACE TEMP TABLE _lfm_key AS
       SELECT artist_norm, full_norm, artist_norm || '::' || full_norm AS fkey,
              arg_max(track_mbid, n) FILTER (WHERE track_mbid IS NOT NULL) AS track_mbid
       FROM (SELECT artist_norm, full_norm, track_mbid, count(*) AS n FROM events
             WHERE track_uri IS NULL GROUP BY 1, 2, 3)
       ANTI JOIN _sp_key USING (artist_norm, full_norm)
       GROUP BY 1, 2""",
    # Spotify tracks enriched without any Spotify play (found for Last.fm-only songs), by their key
    """CREATE OR REPLACE TEMP TABLE _sp_extra AS
       SELECT s.track_uri, s.isrc, na.v AS artist_norm, nt.v AS full_norm
       FROM _sp s ANTI JOIN _uri USING (track_uri)
       JOIN _n_artist na ON na.k = s.artists[1].name
       JOIN _n_title nt ON nt.k = s.name
       WHERE s.isrc IS NOT NULL""",
    """CREATE OR REPLACE TEMP TABLE _lfm_track AS
       SELECT k.artist_norm, k.full_norm,
              coalesce(x.isrc, mb.isrcs[1], ms.isrcs[1], k.fkey) AS track_id,
              CASE WHEN x.isrc IS NOT NULL THEN 'isrc'
                   WHEN coalesce(mb.isrcs[1], ms.isrcs[1]) IS NOT NULL THEN 'mb_isrc' ELSE 'fallback' END AS kind
       FROM _lfm_key k
       LEFT JOIN (SELECT artist_norm, full_norm, min(isrc) AS isrc FROM _sp_extra GROUP BY 1, 2) x
              USING (artist_norm, full_norm)
       LEFT JOIN _mb mb ON mb.lookup_kind = 'mbid' AND mb.lookup_key = k.track_mbid
       LEFT JOIN _mb ms ON ms.lookup_kind = 'search' AND ms.lookup_key = k.fkey AND ms.score >= 90""",
    """INSERT INTO track_key_map
       SELECT artist_norm, full_norm, track_id FROM _sp_key
       UNION ALL SELECT artist_norm, full_norm, track_id FROM _lfm_track""",
    # those Spotify-only-by-lookup URIs describe their track too (title, duration, album, credits)
    """INSERT INTO _uri_track
       SELECT track_uri, 0, isrc, 'isrc' FROM _sp_extra WHERE isrc IN (SELECT track_id FROM _lfm_track)""",
    # kind of each track id, for dim_track.isrc and the printed counts (best kind wins)
    """CREATE OR REPLACE TEMP TABLE _ids AS
       SELECT track_id, arg_min(kind, CASE kind WHEN 'isrc' THEN 1 WHEN 'mb_isrc' THEN 2 ELSE 3 END) AS kind
       FROM (SELECT track_id, kind FROM _uri_track UNION ALL SELECT track_id, kind FROM _lfm_track)
       GROUP BY 1""",
    # --- 3. dim_track -----------------------------------------------------------------------
    # every event with its track, grouped to distinct (track, key, ...) combinations
    """CREATE OR REPLACE TEMP TABLE _ev AS
       SELECT coalesce(u.track_id, k.track_id) AS track_id, e.track_uri IS NOT NULL AS sp,
              e.artist_norm, e.full_norm, e.base_norm, e.mix_desc, e.track_raw, e.track_mbid,
              count(*) AS n
       FROM events e
       LEFT JOIN track_uri_map u ON u.track_uri = e.track_uri
       LEFT JOIN track_key_map k ON e.track_uri IS NULL AND k.artist_norm = e.artist_norm
                                 AND k.full_norm = e.full_norm
       GROUP BY ALL""",
    """CREATE OR REPLACE TEMP TABLE _t_attr AS
       SELECT track_id, artist_norm, full_norm, base_norm, mix_desc FROM (
           SELECT track_id, sp, artist_norm, full_norm, base_norm, mix_desc, sum(n) AS n
           FROM _ev GROUP BY ALL)
       QUALIFY row_number() OVER (PARTITION BY track_id
                                  ORDER BY sp DESC, n DESC, artist_norm, full_norm) = 1""",
    """CREATE OR REPLACE TEMP TABLE _t_raw AS
       SELECT track_id, track_raw FROM (SELECT track_id, track_raw, sum(n) AS n FROM _ev GROUP BY ALL)
       QUALIFY row_number() OVER (PARTITION BY track_id ORDER BY n DESC, track_raw) = 1""",
    """CREATE OR REPLACE TEMP TABLE _t_mbid AS
       SELECT track_id, track_mbid FROM (
           SELECT track_id, track_mbid, sum(n) AS n FROM _ev WHERE track_mbid IS NOT NULL GROUP BY ALL)
       QUALIFY row_number() OVER (PARTITION BY track_id ORDER BY n DESC, track_mbid) = 1""",
    # the most played URI of each track that Spotify knows
    """CREATE OR REPLACE TEMP TABLE _t_sp AS
       SELECT u.track_id, s.* FROM _uri_track u JOIN _sp s USING (track_uri)
       QUALIFY row_number() OVER (PARTITION BY u.track_id ORDER BY u.n DESC, u.track_uri) = 1""",
    """CREATE OR REPLACE TEMP TABLE _t_local AS
       SELECT u.track_id, max(l.duration_ms) AS duration_ms
       FROM _uri_track u JOIN enr_local_duration l USING (track_uri) GROUP BY 1""",
    # MB recordings that describe each track, by priority (isrc, mbid, search)
    """CREATE OR REPLACE TEMP TABLE _t_mb AS
       SELECT a.track_id, 1 AS prio, mb.length_ms, mb.first_release_date
       FROM _t_attr a JOIN _mb mb ON mb.lookup_kind = 'isrc' AND mb.lookup_key = a.track_id
       UNION ALL
       SELECT m.track_id, 2, mb.length_ms, mb.first_release_date
       FROM _t_mbid m JOIN _mb mb ON mb.lookup_kind = 'mbid' AND mb.lookup_key = m.track_mbid
       UNION ALL
       SELECT a.track_id, 3, mb.length_ms, mb.first_release_date
       FROM _t_attr a JOIN _mb mb ON mb.lookup_kind = 'search' AND mb.score >= 90
                                  AND mb.lookup_key = a.artist_norm || '::' || a.full_norm""",
    """CREATE OR REPLACE TEMP TABLE _t_year AS
       SELECT track_id, min(y) AS recording_year FROM (
           SELECT u.track_id, try_cast(left(s.release_date, 4) AS INTEGER) AS y
           FROM _uri_track u JOIN _sp s USING (track_uri)
           UNION ALL
           SELECT track_id, try_cast(left(first_release_date, 4) AS INTEGER) FROM _t_mb)
       WHERE y IS NOT NULL GROUP BY 1""",
    """CREATE OR REPLACE TEMP TABLE _t_dur AS
       SELECT a.track_id,
              CASE WHEN s.duration_ms IS NOT NULL THEN s.duration_ms
                   WHEN l.duration_ms IS NOT NULL THEN l.duration_ms
                   WHEN mb.length_ms IS NOT NULL THEN mb.length_ms
                   WHEN fi.duration_ms IS NOT NULL THEN fi.duration_ms
                   ELSE dz.duration_ms END AS duration_ms,
              CASE WHEN s.duration_ms IS NOT NULL THEN 'spotify'
                   WHEN l.duration_ms IS NOT NULL THEN 'local'
                   WHEN mb.length_ms IS NOT NULL THEN 'musicbrainz'
                   WHEN fi.duration_ms IS NOT NULL THEN 'lastfm'
                   WHEN dz.duration_ms IS NOT NULL THEN 'deezer' END AS duration_source
       FROM _t_attr a
       LEFT JOIN _t_sp s USING (track_id)
       LEFT JOIN _t_local l USING (track_id)
       LEFT JOIN (SELECT track_id, arg_min(length_ms, prio) AS length_ms FROM _t_mb
                  WHERE length_ms IS NOT NULL GROUP BY 1) mb USING (track_id)
       LEFT JOIN enr_lastfm_info fi ON fi.entity_type = 'track' AND fi.http_status = 200
                                    AND fi.entity_key = a.artist_norm || '::' || a.full_norm
       LEFT JOIN enr_deezer_track dz ON dz.isrc = a.track_id AND dz.http_status = 200""",
    # --- 4. artists -------------------------------------------------------------------------
    # Spotify artist credits of every track's most played URI, by position
    """CREATE OR REPLACE TEMP TABLE _t_credit AS
       SELECT track_id, pos, a.id AS spotify_artist_id, a.name, n.v AS artist_norm
       FROM (SELECT track_id, unnest(artists) AS a, generate_subscripts(artists, 1) AS pos FROM _t_sp)
       LEFT JOIN _n_artist n ON n.k = a.name""",
    """CREATE OR REPLACE TEMP TABLE _t_remix AS
       SELECT a.track_id, n.v AS artist_norm FROM _t_attr a JOIN _n_mix n ON n.k = a.mix_desc
       WHERE n.v IS NOT NULL""",
    """CREATE OR REPLACE TEMP TABLE _a_known AS
       SELECT artist_norm FROM _t_attr
       UNION SELECT artist_norm FROM _t_credit WHERE pos >= 2 AND artist_norm <> ''""",
    """CREATE OR REPLACE TEMP TABLE _a_all AS
       SELECT artist_norm FROM _a_known
       UNION SELECT r.artist_norm FROM _t_remix r SEMI JOIN
           (SELECT artist_norm FROM _a_known UNION SELECT DISTINCT artist_norm FROM events) k USING (artist_norm)""",
    """CREATE OR REPLACE TEMP TABLE _a_spid AS
       SELECT artist_norm, spotify_artist_id FROM (
           SELECT n.v AS artist_norm, a.id AS spotify_artist_id, count(*) AS n
           FROM (SELECT unnest(artists) AS a FROM _sp) JOIN _n_artist n ON n.k = a.name
           WHERE a.id IS NOT NULL GROUP BY 1, 2)
       QUALIFY row_number() OVER (PARTITION BY artist_norm ORDER BY n DESC, spotify_artist_id) = 1""",
    """CREATE OR REPLACE TEMP TABLE _a_raw AS
       SELECT artist_norm, artist_raw FROM (
           SELECT artist_norm, artist_raw, count(*) AS n FROM events GROUP BY 1, 2)
       QUALIFY row_number() OVER (PARTITION BY artist_norm ORDER BY n DESC, artist_raw) = 1""",
    """CREATE OR REPLACE TEMP TABLE _a_cname AS
       SELECT artist_norm, name FROM (SELECT artist_norm, name, count(*) AS n FROM _t_credit GROUP BY 1, 2)
       QUALIFY row_number() OVER (PARTITION BY artist_norm ORDER BY n DESC, name) = 1""",
    """CREATE OR REPLACE TEMP TABLE _a_mbid AS
       SELECT artist_norm, artist_mbid FROM (
           SELECT artist_norm, artist_mbid, count(*) AS n FROM events
           WHERE artist_mbid IS NOT NULL GROUP BY 1, 2)
       QUALIFY row_number() OVER (PARTITION BY artist_norm ORDER BY n DESC, artist_mbid) = 1""",
    """CREATE OR REPLACE TEMP TABLE _a_mb_credit AS
       SELECT artist_norm, artist_mbid FROM (
           SELECT n.v AS artist_norm, c.mbid AS artist_mbid, count(*) AS n
           FROM (SELECT unnest(artist_credits) AS c FROM _mb) JOIN _n_artist n ON n.k = c.name
           WHERE c.mbid IS NOT NULL GROUP BY 1, 2)
       QUALIFY row_number() OVER (PARTITION BY artist_norm ORDER BY n DESC, artist_mbid) = 1""",
    """INSERT INTO dim_artist
       SELECT row_number() OVER (ORDER BY a.artist_norm) AS artist_id,
              coalesce(sa.name, r.artist_raw, c.name, a.artist_norm) AS name,
              a.artist_norm,
              coalesce(m.artist_mbid, mc.artist_mbid) AS artist_mbid,
              sp.spotify_artist_id,
              ma.country, ma.type, ma.begin_year, ma.end_year,
              fi.listeners
       FROM _a_all a
       LEFT JOIN _a_spid sp USING (artist_norm)
       LEFT JOIN enr_spotify_artist sa ON sa.spotify_artist_id = sp.spotify_artist_id AND sa.http_status = 200
       LEFT JOIN _a_raw r USING (artist_norm)
       LEFT JOIN _a_cname c USING (artist_norm)
       LEFT JOIN _a_mbid m USING (artist_norm)
       LEFT JOIN _a_mb_credit mc USING (artist_norm)
       LEFT JOIN enr_mb_artist ma ON ma.artist_mbid = coalesce(m.artist_mbid, mc.artist_mbid)
                                  AND ma.http_status = 200
       LEFT JOIN enr_lastfm_info fi ON fi.entity_type = 'artist' AND fi.entity_key = a.artist_norm
                                    AND fi.http_status = 200""",
    # --- 6. albums --------------------------------------------------------------------------
    """CREATE OR REPLACE TEMP TABLE _al AS
       SELECT album_spotify_id, name, album_type, release_date, first_artist FROM (
           SELECT album_spotify_id, album_name AS name, album_type, release_date,
                  n.v AS first_artist, count(*) OVER (PARTITION BY album_spotify_id, n.v) AS n, track_uri
           FROM _sp LEFT JOIN _n_artist n ON n.k = artists[1].name WHERE album_spotify_id IS NOT NULL)
       QUALIFY row_number() OVER (PARTITION BY album_spotify_id ORDER BY n DESC, first_artist, track_uri) = 1""",
    """INSERT INTO dim_album
       SELECT row_number() OVER (ORDER BY al.album_spotify_id) AS album_id,
              coalesce(al.name, ''), coalesce(n.v, ''), ar.artist_id, al.album_type, al.release_date,
              try_cast(left(al.release_date, 4) AS INTEGER), al.album_spotify_id, NULL
       FROM _al al LEFT JOIN dim_artist ar ON ar.artist_norm = al.first_artist
       LEFT JOIN _n_album n ON n.k = al.name""",
    # --- 3 (cont). dim_track ------------------------------------------------------------------
    """INSERT INTO dim_track
       SELECT a.track_id,
              CASE WHEN a.track_id IN (SELECT track_id FROM _ids WHERE kind <> 'fallback') THEN a.track_id END,
              coalesce(s.name, r.track_raw),
              a.artist_norm, a.full_norm, a.base_norm, a.mix_desc,
              a.mix_desc IS NOT NULL AND NOT list_contains($generic, a.mix_desc),
              a.artist_norm || '::' || a.base_norm,
              ar.artist_id,
              al.album_id,
              d.duration_ms, d.duration_source,
              y.recording_year,
              min(y.recording_year) OVER (PARTITION BY a.artist_norm || '::' || a.base_norm),
              coalesce(d.duration_ms > 1200000
                       OR (d.duration_ms > 600000 AND regexp_matches(a.full_norm, '\\b(mix|set|live)\\b')),
                       false),
              fi.listeners
       FROM _t_attr a
       JOIN dim_artist ar USING (artist_norm)
       LEFT JOIN _t_raw r USING (track_id)
       LEFT JOIN _t_sp s USING (track_id)
       LEFT JOIN dim_album al ON al.spotify_album_id = s.album_spotify_id
       LEFT JOIN _t_dur d USING (track_id)
       LEFT JOIN _t_year y USING (track_id)
       LEFT JOIN enr_lastfm_info fi ON fi.entity_type = 'track' AND fi.http_status = 200
                                    AND fi.entity_key = a.artist_norm || '::' || a.full_norm""",
    # --- 5. bridge ----------------------------------------------------------------------------
    """INSERT INTO bridge_track_artist
       SELECT track_id, primary_artist_id, 'primary', 1 FROM dim_track
       UNION ALL
       SELECT track_id, artist_id, 'featured', row_number() OVER (PARTITION BY track_id ORDER BY pos) FROM (
           SELECT c.track_id, ar.artist_id, min(c.pos) AS pos
           FROM _t_credit c JOIN dim_artist ar USING (artist_norm)
           WHERE c.pos >= 2 GROUP BY 1, 2)
       UNION ALL
       SELECT x.track_id, ar.artist_id, 'remixer', 1
       FROM _t_remix x JOIN dim_artist ar USING (artist_norm)""",
]

def run(con: duckdb.DuckDBPyConnection) -> None:
    for t in TABLES:
        con.execute(f"DELETE FROM {t}")
    for sql in STEPS:
        if "_uri AS" in sql:  # _sp and _mb exist now; build the normalised lookups
            for table in LOOKUPS:
                _lookup(con, table)
        if "$generic" in sql:
            con.execute(sql, {"generic": sorted(GENERIC_MIX)})
        else:
            con.execute(sql)
    kinds = dict(con.execute("SELECT kind, count(*) FROM _ids SEMI JOIN dim_track USING (track_id) GROUP BY 1")
                 .fetchall())
    counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in reversed(TABLES)}
    print(f"  dims: tracks isrc={kinds.get('isrc', 0)} mb_isrc={kinds.get('mb_isrc', 0)} "
          f"fallback={kinds.get('fallback', 0)}")
    print("  dims: " + " ".join(f"{t}={n}" for t, n in counts.items()))
