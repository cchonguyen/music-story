"""W0: the schema contract applies cleanly and is idempotent."""

from helpers import fresh_db

from pipeline import config

EXPECTED = {
    "raw_spotify", "raw_lastfm", "stg_spotify", "stg_lastfm", "lfm_self_dupes", "match_links", "events",
    "enr_local_duration", "enr_spotify_track", "enr_spotify_artist", "enr_mb_recording", "enr_mb_artist",
    "enr_lastfm_tags", "enr_lastfm_info", "enr_deezer_track", "enr_deezer_match", "dim_artist", "dim_album", "dim_track",
    "bridge_track_artist", "track_uri_map", "track_key_map", "sessions", "plays", "skips", "genre_map",
    "track_genre",
}


def tables(con) -> set[str]:
    return {r[0] for r in con.execute("SHOW TABLES").fetchall()}


def test_schema_creates_every_contract_table():
    assert tables(fresh_db()) == EXPECTED


def test_schema_is_idempotent():
    con = fresh_db()
    con.execute(config.SCHEMA_SQL.read_text())
    assert tables(con) == EXPECTED


def test_plays_and_skips_share_columns():
    con = fresh_db()
    cols = lambda t: con.execute(f"DESCRIBE {t}").fetchall()
    assert [c[:2] for c in cols("plays")] == [c[:2] for c in cols("skips")]


def test_raw_spotify_never_has_ip_addr():
    con = fresh_db()
    assert "ip_addr" not in {c[0] for c in con.execute("DESCRIBE raw_spotify").fetchall()}


def test_cache_schema_applies_to_sqlite():
    import sqlite3

    db = sqlite3.connect(":memory:")
    db.executescript(config.CACHE_SCHEMA_SQL.read_text())
    db.executescript(config.CACHE_SCHEMA_SQL.read_text())
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert names == {"http_cache", "fetch_queue", "api_pause", "request_log", "api_limit"}


def test_genre_map_columns():
    con = fresh_db()
    cols = [(r[0], r[1], r[2]) for r in con.execute("DESCRIBE genre_map").fetchall()]
    assert cols == [
        ("tag", "VARCHAR", "NO"),
        ("style", "VARCHAR", "YES"),
        ("parent_genre", "VARCHAR", "YES"),
        ("is_genre", "BOOLEAN", "NO"),
        ("is_umbrella", "BOOLEAN", "NO"),
    ]

