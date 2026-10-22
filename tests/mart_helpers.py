"""Shared setup for mart tests: copy the fixture's expected stage 1-3 tables into
memory and run one sql/marts/*.sql file over them."""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline import config

INPUT_TABLES = ["plays", "skips", "sessions", "dim_artist", "dim_album", "dim_track", "bridge_track_artist",
                "track_genre", "genre_map", "fixture_scenarios"]


def mart_db(fixture_db_path: Path, mart_file: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"ATTACH '{fixture_db_path}' AS fx (READ_ONLY)")
    for t in INPUT_TABLES:
        con.execute(f"CREATE TABLE {t} AS SELECT * FROM fx.{t}")
    con.execute("DETACH fx")
    con.execute((config.SQL_DIR / "marts" / mart_file).read_text())
    return con


def columns(con: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    return [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]


def diff_count(con: duckdb.DuckDBPyConnection, got: str, want: str) -> int:
    """Rows in either query but not both (symmetric difference). 0 means equal."""
    return con.execute(f"""SELECT count(*) FROM (
        (({got}) EXCEPT ALL ({want})) UNION ALL (({want}) EXCEPT ALL ({got})))""").fetchone()[0]
