"""Mart rows for the site's data loaders. `uv run python -m pipeline.site_data <name>` prints JSON."""

from __future__ import annotations

import datetime as dt
import decimal
import json
import os
import sys
from pathlib import Path

import duckdb

from pipeline import config

# The site only shows the top of these marts; trimming here keeps page data small on real history.
SITE_FILTERS = {
    "artist_year": "rank <= 50",
    "track_year": "rank <= 50",
    "binge": "window_plays >= 15",
}

INPUT_TABLES = ["plays", "skips", "sessions", "dim_artist", "dim_album", "dim_track", "bridge_track_artist",
                "track_genre", "genre_map", "fixture_scenarios"]


def fixture_inputs(fixture_db_path: Path) -> duckdb.DuckDBPyConnection:
    """In-memory copy of the fixture's input tables (the expected stage 1-3 output)."""
    con = duckdb.connect()
    con.execute(f"ATTACH '{fixture_db_path}' AS fx (READ_ONLY)")
    for t in INPUT_TABLES:
        con.execute(f"CREATE TABLE {t} AS SELECT * FROM fx.{t}")
    con.execute("DETACH fx")
    return con


def fixture_marts(fixture_db_path: Path, mart_file: str | None = None) -> duckdb.DuckDBPyConnection:
    """In-memory copy of the fixture's input tables with marts built (one file, or all in name order)."""
    con = fixture_inputs(fixture_db_path)
    marts = config.SQL_DIR / "marts"
    files = [marts / mart_file] if mart_file else sorted(marts.glob("*.sql"))
    for f in files:
        con.execute(f.read_text())
    return con


def mart_rows(name: str, db: Path | None = None) -> list[dict]:
    if not name.isidentifier():
        raise ValueError(f"bad mart name: {name!r}")
    db = db or (Path(os.environ["SITE_DB"]) if os.environ.get("SITE_DB") else None)
    if db is not None:
        con = duckdb.connect(str(db), read_only=True)
    else:
        con = fixture_marts(config.FIXTURE_DB)
    try:
        where = f"WHERE {SITE_FILTERS[name]}" if name in SITE_FILTERS else ""
        cur = con.execute(f"SELECT * FROM mart_{name} {where} ORDER BY ALL")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()


def _json_default(o):
    if isinstance(o, (dt.date, dt.datetime, dt.time)):
        return o.isoformat()
    if isinstance(o, decimal.Decimal):
        return float(o)
    raise TypeError(type(o))


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m pipeline.site_data <name>", file=sys.stderr)
        return 2
    json.dump(mart_rows(argv[0]), sys.stdout, default=_json_default)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
