"""Step 02: fill norm columns on the staging tables, link Spotify plays to Last.fm
scrobbles (two passes, greedy 1-to-1), link leftovers with pass 3, move double
scrobbles (twins) to lfm_self_dupes, and rewrite match_links and events.

Rules: specs/W2_match.md and the docstring of tests/golden/match_cases.py.
"""

from __future__ import annotations

import duckdb
import pyarrow as pa
from rapidfuzz.distance import Indel
from rapidfuzz.fuzz import token_set_ratio

from pipeline.normalize import is_generic_mix, normalize_artist, normalize_title

WINDOW_SEC = 180       # pass 1: scrobble in [start - 3 min, end + 3 min]
PASS2_GAP_SEC = 90     # pass 2: |scrobble - start| <= 90 s
TWIN_SEC = 360         # twin: unmatched scrobble this close to a matched one of the same song
PASS3_GAP_SEC = 3600   # pass 3: |scrobble - start| <= 1 h, leftovers only (iPhone clock offsets)
ARTIST_MIN = 85
TITLE_MIN = 92
LFM_EVENT_OFFSET = 1_000_000_000_000


def _ratio(a: str, b: str) -> float:
    return Indel.normalized_similarity(a, b) * 100


def fill_norms(con: duckdb.DuckDBPyConnection) -> None:
    artists = [r[0] for r in con.execute(
        "SELECT DISTINCT artist_raw FROM stg_spotify UNION SELECT DISTINCT artist_raw FROM stg_lastfm").fetchall()]
    titles = [r[0] for r in con.execute(
        "SELECT DISTINCT track_raw FROM stg_spotify UNION SELECT DISTINCT track_raw FROM stg_lastfm").fetchall()]
    artists = [a for a in artists if a is not None]
    titles = [t for t in titles if t is not None]
    norm_titles = [normalize_title(t) for t in titles]
    artist_map = pa.table({"raw": pa.array(artists, pa.string()),
                           "artist_norm": pa.array([normalize_artist(a) for a in artists], pa.string())})
    title_map = pa.table({"raw": pa.array(titles, pa.string()),
                          "full_norm": pa.array([n[0] for n in norm_titles], pa.string()),
                          "base_norm": pa.array([n[1] for n in norm_titles], pa.string()),
                          "mix_desc": pa.array([n[2] for n in norm_titles], pa.string())})
    con.register("_artist_map", artist_map)
    con.register("_title_map", title_map)
    for t in ("stg_spotify", "stg_lastfm"):
        con.execute(f"UPDATE {t} SET artist_norm = coalesce((SELECT m.artist_norm FROM _artist_map m "
                    f"WHERE m.raw = {t}.artist_raw), '')")
        con.execute(f"""UPDATE {t} SET full_norm = coalesce(m.full_norm, ''), base_norm = coalesce(m.base_norm, ''),
                        mix_desc = m.mix_desc
                        FROM _title_map m WHERE m.raw = {t}.track_raw""")
        con.execute(f"UPDATE {t} SET full_norm = '', base_norm = '', mix_desc = NULL WHERE track_raw IS NULL")
    con.unregister("_artist_map")
    con.unregister("_title_map")


CANDIDATES_SQL = f"""
WITH pairs AS (
    SELECT s.sp_id, l.lfm_id FROM stg_spotify s JOIN stg_lastfm l
      ON s.artist_norm = l.artist_norm AND s.artist_norm <> ''
     AND l.scrobbled_at_utc BETWEEN s.started_at_utc - INTERVAL {WINDOW_SEC} SECOND
                                AND s.ended_at_utc + INTERVAL {WINDOW_SEC} SECOND
    UNION
    SELECT s.sp_id, l.lfm_id FROM stg_spotify s JOIN stg_lastfm l
      ON s.base_norm = l.base_norm AND s.base_norm <> ''
     AND l.scrobbled_at_utc BETWEEN s.started_at_utc - INTERVAL {WINDOW_SEC} SECOND
                                AND s.ended_at_utc + INTERVAL {WINDOW_SEC} SECOND
)
SELECT p.sp_id, p.lfm_id, s.is_full_listen,
       s.artist_norm, s.full_norm, s.base_norm, s.mix_desc,
       l.artist_norm, l.full_norm, l.base_norm, l.mix_desc,
       (epoch_us(l.scrobbled_at_utc) - epoch_us(s.started_at_utc)) / 1e6 AS gap
FROM pairs p JOIN stg_spotify s USING (sp_id) JOIN stg_lastfm l USING (lfm_id)
"""


def score_candidates(rows: list[tuple]) -> list[tuple]:
    """(sp_id, lfm_id, is_full, pass, gap, score) for every pair that passes pass 1 or pass 2."""
    out = []
    artist_cache: dict[tuple[str, str], bool] = {}
    for sp_id, lfm_id, is_full, s_art, s_full, s_base, s_mix, l_art, l_full, l_base, l_mix, gap in rows:
        key = (s_art, l_art)
        ok = artist_cache.get(key)
        if ok is None:
            ok = artist_cache[key] = s_art == l_art or token_set_ratio(s_art, l_art) >= ARTIST_MIN
        if not ok:
            continue
        score = 100.0 if s_full == l_full else _ratio(s_full, l_full)
        if score >= TITLE_MIN:
            out.append((sp_id, lfm_id, is_full, 1, gap, score))
            continue
        if abs(gap) > PASS2_GAP_SEC:
            continue
        if not (is_generic_mix(s_mix) or is_generic_mix(l_mix) or s_mix == l_mix):
            continue
        score = 100.0 if s_base == l_base else _ratio(s_base, l_base)
        if score >= TITLE_MIN:
            out.append((sp_id, lfm_id, is_full, 2, gap, score))
    return out


def greedy(cands: list[tuple]) -> list[tuple]:
    cands.sort(key=lambda c: (not c[2], c[3], abs(c[4]), -c[5], c[0], c[1]))
    used_sp: set[int] = set()
    used_lf: set[int] = set()
    links = []
    for sp_id, lfm_id, _full, p, gap, score in cands:
        if sp_id in used_sp or lfm_id in used_lf:
            continue
        used_sp.add(sp_id)
        used_lf.add(lfm_id)
        links.append((sp_id, lfm_id, p, gap, score))
    return links


TWINS_SQL = f"""
INSERT INTO lfm_self_dupes
SELECT DISTINCT ON (u.lfm_id) u.lfm_id, k.lfm_id,
       abs(epoch(u.scrobbled_at_utc) - epoch(k.scrobbled_at_utc))
FROM stg_lastfm u JOIN stg_lastfm k
  ON k.artist_norm = u.artist_norm AND k.full_norm = u.full_norm
 AND u.artist_norm <> '' AND u.full_norm <> '' AND k.lfm_id <> u.lfm_id
 AND abs(epoch(u.scrobbled_at_utc) - epoch(k.scrobbled_at_utc)) <= {TWIN_SEC}
WHERE u.lfm_id NOT IN (SELECT lfm_id FROM match_links)
  AND k.lfm_id IN (SELECT lfm_id FROM match_links)
ORDER BY u.lfm_id, abs(epoch(u.scrobbled_at_utc) - epoch(k.scrobbled_at_utc)), k.lfm_id
"""

PASS3_SQL = f"""
SELECT s.sp_id, l.lfm_id, s.mix_desc, l.mix_desc,
       (epoch_us(l.scrobbled_at_utc) - epoch_us(s.started_at_utc)) / 1e6 AS gap
FROM stg_spotify s JOIN stg_lastfm l
  ON s.artist_norm = l.artist_norm AND s.base_norm = l.base_norm
 AND s.artist_norm <> '' AND s.base_norm <> ''
 AND l.scrobbled_at_utc BETWEEN s.started_at_utc - INTERVAL {PASS3_GAP_SEC} SECOND
                            AND s.started_at_utc + INTERVAL {PASS3_GAP_SEC} SECOND
WHERE s.is_full_listen
  AND s.sp_id NOT IN (SELECT sp_id FROM match_links)
  AND l.lfm_id NOT IN (SELECT lfm_id FROM match_links)
"""


def pass3(rows: list[tuple]) -> list[tuple]:
    """Greedy 1-to-1 over leftover pairs with equal names, nearest first."""
    cands = [(sp, lf, gap) for sp, lf, s_mix, l_mix, gap in rows
             if is_generic_mix(s_mix) or is_generic_mix(l_mix) or s_mix == l_mix]
    cands.sort(key=lambda c: (abs(c[2]), c[0], c[1]))
    used_sp: set[int] = set()
    used_lf: set[int] = set()
    links = []
    for sp_id, lfm_id, gap in cands:
        if sp_id in used_sp or lfm_id in used_lf:
            continue
        used_sp.add(sp_id)
        used_lf.add(lfm_id)
        links.append((sp_id, lfm_id, 3, gap, 100.0))
    return links


def _insert_links(con: duckdb.DuckDBPyConnection, links: list[tuple]) -> None:
    tbl = pa.table({
        "sp_id": pa.array([r[0] for r in links], pa.int64()),
        "lfm_id": pa.array([r[1] for r in links], pa.int64()),
        "match_pass": pa.array([r[2] for r in links], pa.int8()),
        "match_gap_sec": pa.array([float(r[3]) for r in links], pa.float64()),
        "fuzzy_score": pa.array([float(r[4]) for r in links], pa.float64()),
    })
    con.register("_links", tbl)
    con.execute("INSERT INTO match_links SELECT * FROM _links")
    con.unregister("_links")


EVENTS_SQL = f"""
INSERT INTO events
SELECT s.sp_id AS event_id, s.sp_id, m.lfm_id,
       CASE WHEN m.lfm_id IS NULL THEN 'spotify' ELSE 'both' END AS source,
       s.started_at_utc, s.ended_at_utc, s.ms_played,
       m.lfm_id IS NULL AND s.ms_played < 30000 AS is_skip,
       s.track_uri,
       coalesce(s.artist_raw, l.artist_raw, ''), coalesce(s.track_raw, l.track_raw, ''),
       coalesce(s.album_raw, l.album_raw),
       s.artist_norm, s.full_norm, s.base_norm, s.mix_desc,
       l.track_mbid, l.artist_mbid, m.match_pass, m.match_gap_sec
FROM stg_spotify s
LEFT JOIN match_links m USING (sp_id)
LEFT JOIN stg_lastfm l ON l.lfm_id = m.lfm_id
UNION ALL
SELECT {LFM_EVENT_OFFSET} + l.lfm_id, NULL, l.lfm_id, 'lastfm',
       l.scrobbled_at_utc, NULL, NULL, false, NULL,
       l.artist_raw, l.track_raw, l.album_raw,
       l.artist_norm, l.full_norm, l.base_norm, l.mix_desc,
       l.track_mbid, l.artist_mbid, NULL, NULL
FROM stg_lastfm l
WHERE NOT EXISTS (SELECT 1 FROM match_links m WHERE m.lfm_id = l.lfm_id)
"""


def run(con: duckdb.DuckDBPyConnection) -> None:
    fill_norms(con)
    links = greedy(score_candidates(con.execute(CANDIDATES_SQL).fetchall()))

    con.execute("DELETE FROM events")
    con.execute("DELETE FROM match_links")
    _insert_links(con, links)

    links3 = pass3(con.execute(PASS3_SQL).fetchall())
    _insert_links(con, links3)
    links += links3

    # Twins leave stg_lastfm, like step 01's self-dupes. Re-runs find none left.
    before = con.execute("SELECT count(*) FROM lfm_self_dupes").fetchone()[0]
    con.execute(TWINS_SQL)
    con.execute("DELETE FROM stg_lastfm WHERE lfm_id IN (SELECT lfm_id FROM lfm_self_dupes)")
    n_twins = con.execute("SELECT count(*) FROM lfm_self_dupes").fetchone()[0] - before
    con.execute(EVENTS_SQL)

    n_sp, n_lf = con.execute("SELECT (SELECT count(*) FROM stg_spotify), (SELECT count(*) FROM stg_lastfm)").fetchone()
    p1 = sum(1 for r in links if r[2] == 1)
    p2 = sum(1 for r in links if r[2] == 2)
    p3 = len(links3)
    gate1 = con.execute("""SELECT avg((m.lfm_id IS NOT NULL)::INT) FROM stg_lastfm l
                           LEFT JOIN match_links m USING (lfm_id)
                           WHERE year(l.scrobbled_at_utc) BETWEEN 2023 AND 2026""").fetchone()[0]
    gate1_txt = "n/a" if gate1 is None else f"{gate1:.2%}"
    print(f"  match: pass1={p1} pass2={p2} pass3={p3} twins={n_twins} unmatched spotify={n_sp - len(links)} "
          f"unmatched lastfm={n_lf - len(links)} gate1(2023-2026)={gate1_txt}")
