"""Run the Stage 1-3 pipeline in order, stopping at the first step not built yet.

    uv run python -m pipeline.build_pipeline                 # real data -> MUSIC_DB
    uv run python -m pipeline.build_pipeline --fixtures      # fixtures/raw -> build/fixture_run.duckdb
    uv run python -m pipeline.build_pipeline --from 05       # resume at a step
    uv run python -m pipeline.build_pipeline --summary       # row counts only

SQL steps see three DuckDB variables: getvariable('data_dir'),
getvariable('repo_root') and getvariable('country_tz_csv').
Python steps are modules exposing run(con: duckdb.DuckDBPyConnection) -> None.

Fetching from APIs is NOT a step here. It is a separate, resumable, long job:
    uv run python -m pipeline.enrich fetch
Step 03 only parses the HTTP cache into the enr_* tables.

Never print raw rows from this script; it reports counts only.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import time
from pathlib import Path

import duckdb

from pipeline import config

# (id, packet, kind, target). kind is "sql" (path under sql/) or "py" (module).
STEPS = [
    ("00", "W0", "sql", "schema.sql"),
    ("01", "W1", "sql", "01_ingest.sql"),
    ("02", "W2", "py", "pipeline.match"),
    ("03", "W3", "py", "pipeline.enrich"),
    ("04", "W7", "py", "pipeline.dims"),
    ("05", "W8", "sql", "05_sessions.sql"),
    ("06", "W9", "py", "pipeline.genre"),
    ("07", "W5/W6", "sql", "marts"),  # every sql/marts/*.sql, in name order
]

SUMMARY_TABLES = ["raw_spotify", "raw_lastfm", "stg_spotify", "stg_lastfm", "lfm_self_dupes", "match_links",
                  "events", "enr_spotify_track", "enr_lastfm_tags", "dim_artist", "dim_track", "sessions",
                  "plays", "skips", "track_genre"]


def available(kind: str, target: str) -> bool:
    if kind == "sql":
        path = config.SQL_DIR / target
        return path.is_dir() and any(path.glob("*.sql")) if target == "marts" else path.exists()
    try:
        importlib.import_module(target)
        return True
    except ModuleNotFoundError as e:
        if e.name == target:
            return False
        raise


def run_step(con: duckdb.DuckDBPyConnection, kind: str, target: str) -> None:
    if kind == "py":
        importlib.import_module(target).run(con)
        return
    path = config.SQL_DIR / target
    files = sorted(path.glob("*.sql")) if path.is_dir() else [path]
    for f in files:
        con.execute(f.read_text())


def fixture_enrichment(con: duckdb.DuckDBPyConnection) -> None:
    """Step 03 for --fixtures: copy the fixture's parsed enr_* tables instead of reading CACHE_DIR."""
    con.execute(f"ATTACH '{config.FIXTURE_DB}' AS fx (READ_ONLY)")
    tables = [r[0] for r in con.execute(
        "SELECT table_name FROM duckdb_tables() WHERE database_name = 'fx' AND table_name LIKE 'enr_%'").fetchall()]
    for t in tables:
        con.execute(f"DELETE FROM {t}")
        con.execute(f"INSERT INTO {t} SELECT * FROM fx.{t}")
    con.execute("DETACH fx")


def summary(con: duckdb.DuckDBPyConnection) -> None:
    for t in SUMMARY_TABLES:
        try:
            n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        except duckdb.CatalogException:
            n = "-"
        print(f"  {t:<20} {n}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixtures", action="store_true", help="read fixtures/raw instead of DATA_DIR")
    ap.add_argument("--db", type=Path, help="database path (default MUSIC_DB, or build/fixture_run.duckdb)")
    ap.add_argument("--from", dest="start", default="00", help="first step id to run")
    ap.add_argument("--to", dest="stop", default="99", help="last step id to run")
    ap.add_argument("--summary", action="store_true", help="print table counts and exit")
    args = ap.parse_args(argv)

    data_dir = config.FIXTURE_RAW_DIR if args.fixtures else config.DATA_DIR
    db = args.db or (config.REPO_ROOT / "build" / "fixture_run.duckdb" if args.fixtures else config.MUSIC_DB)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db))
    if args.summary:
        summary(con)
        return 0
    if data_dir is None:
        print("DATA_DIR is not set. Put it in .env or pass --fixtures.", file=sys.stderr)
        return 2
    con.execute("SET VARIABLE data_dir = ?", [str(data_dir)])
    con.execute("SET VARIABLE repo_root = ?", [str(config.REPO_ROOT)])
    con.execute("SET VARIABLE country_tz_csv = ?", [str(config.COUNTRY_TZ_CSV)])

    print(f"db={db}  data={data_dir}")
    for sid, packet, kind, target in STEPS:
        if not (args.start <= sid <= args.stop):
            continue
        if not available(kind, target):
            print(f"step {sid} ({target}) not built yet, owned by {packet}. Stopping.")
            break
        t0 = time.time()
        if args.fixtures and target == "pipeline.enrich":
            fixture_enrichment(con)  # never parse the real API cache into a fixture run
        else:
            run_step(con, kind, target)
        print(f"step {sid} {target} done in {time.time() - t0:.1f}s")
    summary(con)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
