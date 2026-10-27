"""Mart rows for the site's data loaders. `uv run python -m pipeline.site_data <name>` prints JSON;
`--parquet <view>` writes one of PARQUET_EXPORTS as Parquet to stdout."""

from __future__ import annotations

import datetime as dt
import decimal
import json
import os
import sys
import tempfile
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


def fixture_marts(fixture_db_path: Path, mart_file: str | None = None) -> duckdb.DuckDBPyConnection:
    """In-memory copy of the fixture's input tables with marts built (one file, or all in name order)."""
    con = duckdb.connect()
    con.execute(f"ATTACH '{fixture_db_path}' AS fx (READ_ONLY)")
    for t in INPUT_TABLES:
        con.execute(f"CREATE TABLE {t} AS SELECT * FROM fx.{t}")
    con.execute("DETACH fx")
    marts = config.SQL_DIR / "marts"
    files = [marts / mart_file] if mart_file else sorted(marts.glob("*.sql"))
    for f in files:
        con.execute(f.read_text())
    return con


# Parquet exports for DuckDB-Wasm pages: view name -> sort order. Sorting groups repeated names,
# which shrinks the dictionary-encoded Zstd file.
PARQUET_EXPORTS = {
    "explorer_plays": "artist, album, title, ts",
}


def _site_con(db: Path | None) -> duckdb.DuckDBPyConnection:
    db = db or (Path(os.environ["SITE_DB"]) if os.environ.get("SITE_DB") else None)
    if db is not None:
        return duckdb.connect(str(db), read_only=True)
    return fixture_marts(config.FIXTURE_DB)


def mart_rows(name: str, db: Path | None = None) -> list[dict]:
    if not name.isidentifier():
        raise ValueError(f"bad mart name: {name!r}")
    con = _site_con(db)
    try:
        where = f"WHERE {SITE_FILTERS[name]}" if name in SITE_FILTERS else ""
        cur = con.execute(f"SELECT * FROM mart_{name} {where} ORDER BY ALL")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()


def parquet_bytes(name: str, db: Path | None = None) -> bytes:
    """One of PARQUET_EXPORTS as a Zstd Parquet file."""
    order = PARQUET_EXPORTS[name]
    con = _site_con(db)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / f"{name}.parquet"
            con.execute(f"COPY (SELECT * FROM {name} ORDER BY {order}) TO '{out}' "
                        "(FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 122880)")
            return out.read_bytes()
    finally:
        con.close()


def _json_default(o):
    if isinstance(o, (dt.date, dt.datetime, dt.time)):
        return o.isoformat()
    if isinstance(o, decimal.Decimal):
        return float(o)
    raise TypeError(type(o))


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--parquet":
        sys.stdout.buffer.write(parquet_bytes(argv[1]))
        return 0
    if len(argv) != 1:
        print("usage: python -m pipeline.site_data <name> | --parquet <view>", file=sys.stderr)
        return 2
    json.dump(mart_rows(argv[0]), sys.stdout, default=_json_default)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
