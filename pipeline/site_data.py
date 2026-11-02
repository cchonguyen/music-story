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
                "track_genre", "genre_map", "enr_deezer_track", "fixture_scenarios"]


def fixture_marts(fixture_db_path: Path, mart_file: str | None = None) -> duckdb.DuckDBPyConnection:
    """Copy of the fixture's input tables with marts built (one file, or all in name order).
    When building all marts for the default fixture DB, caches the materialized DuckDB file
    so 16+ Observable Framework loaders do not rebuild every mart 16 times."""
    marts = config.SQL_DIR / "marts"
    files = [marts / mart_file] if mart_file else sorted(marts.glob("*.sql"))
    if mart_file is None and fixture_db_path == config.FIXTURE_DB and fixture_db_path.exists():
        cache_db = config.REPO_ROOT / "build" / "fixture_marts_cache.duckdb"
        src_mtime = max([fixture_db_path.stat().st_mtime, *[f.stat().st_mtime for f in files]])
        if cache_db.exists() and cache_db.stat().st_mtime >= src_mtime:
            return duckdb.connect(str(cache_db), read_only=True)
        cache_db.parent.mkdir(parents=True, exist_ok=True)
        if cache_db.exists():
            cache_db.unlink()
        con = duckdb.connect(str(cache_db))
        con.execute(f"ATTACH '{fixture_db_path}' AS fx (READ_ONLY)")
        for t in INPUT_TABLES:
            con.execute(f"CREATE TABLE {t} AS SELECT * FROM fx.{t}")
        con.execute("DETACH fx")
        for f in files:
            con.execute(f.read_text())
        con.close()
        return duckdb.connect(str(cache_db), read_only=True)

    con = duckdb.connect()
    con.execute(f"ATTACH '{fixture_db_path}' AS fx (READ_ONLY)")
    for t in INPUT_TABLES:
        con.execute(f"CREATE TABLE {t} AS SELECT * FROM fx.{t}")
    con.execute("DETACH fx")
    for f in files:
        con.execute(f.read_text())
    return con


# Parquet exports for DuckDB-Wasm pages: view name -> sort order. Sorting groups repeated names,
# which shrinks the dictionary-encoded Zstd file.
PARQUET_EXPORTS = {
    "explorer_plays": "artist, album, title, day",
}
MAX_PARQUET_BYTES = 20 * 1024 * 1024  # 20 MiB safety ceiling below Cloudflare Workers 25 MiB limit


def _site_con(db: Path | None) -> duckdb.DuckDBPyConnection:
    db = db or (Path(os.environ["SITE_DB"]) if os.environ.get("SITE_DB") else None)
    if db is not None:
        con = duckdb.connect(str(db), read_only=True)
        has_day = con.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'explorer_plays' AND column_name = 'day'"
        ).fetchone()[0] > 0
        has_pulse = con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'mart_tempo_pulse'"
        ).fetchone()[0] > 0
        has_xray = con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'mart_genre_xray'"
        ).fetchone()[0] > 0
        has_plays = con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'plays'"
        ).fetchone()[0] > 0
        has_genre_map = con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'genre_map'"
        ).fetchone()[0] > 0
        is_fresh_genre = True
        if has_plays and has_genre_map:
            db_parents = {r[0] for r in con.execute("SELECT DISTINCT parent_genre FROM genre_map WHERE is_genre").fetchall()}
            from pipeline.genre import PARENTS
            is_fresh_genre = db_parents.issubset(set(PARENTS)) and len(db_parents) == len(PARENTS)
        if (has_day and has_pulse and has_xray and is_fresh_genre) or not has_plays:
            return con
        con.close()
        con_rw = duckdb.connect(str(db))
        if has_plays and not is_fresh_genre:
            from pipeline import genre
            genre.run(con_rw)
        for f in sorted((config.SQL_DIR / "marts").glob("*.sql")):
            con_rw.execute(f.read_text())
        con_rw.close()
        return duckdb.connect(str(db), read_only=True)
    return fixture_marts(config.FIXTURE_DB)


def mart_rows(name: str, db: Path | None = None) -> list[dict]:
    if not name.isidentifier():
        raise ValueError(f"bad mart name: {name!r}")
    con = _site_con(db)
    try:
        table, where = name, f"WHERE {SITE_FILTERS[name]}" if name in SITE_FILTERS else ""
        cur = con.execute(f"SELECT * FROM mart_{table} {where} ORDER BY ALL")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()


def parquet_bytes(name: str, db: Path | None = None, max_bytes: int = MAX_PARQUET_BYTES) -> bytes:
    """One of PARQUET_EXPORTS as a Zstd Parquet file."""
    order = PARQUET_EXPORTS[name]
    con = _site_con(db)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / f"{name}.parquet"
            con.execute(f"COPY (SELECT * FROM {name} ORDER BY {order}) TO '{out}' "
                        "(FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 122880)")
            data = out.read_bytes()
            if len(data) > max_bytes:
                raise ValueError(
                    f"Parquet export {name!r} is {len(data)} bytes, exceeding max_bytes={max_bytes}"
                )
            return data
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
