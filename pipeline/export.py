"""W12: write export_plays as Zstd Parquet. `uv run python -m pipeline.export [--out PATH]`.

Reads export_plays from SITE_DB when set (built by step 08), else builds it in memory from the
fixture. Writes to stdout by default, which is what the site's data loader expects.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

import duckdb

from pipeline import config
from pipeline.site_data import fixture_inputs

EXPORT_SQL = config.SQL_DIR / "08_export.sql"


def fixture_export(fixture_db_path: Path) -> duckdb.DuckDBPyConnection:
    """In-memory fixture inputs with export_plays built."""
    con = fixture_inputs(fixture_db_path)
    con.execute(EXPORT_SQL.read_text())
    return con


def write_parquet(out: Path, db: Path | None = None) -> None:
    db = db or (Path(os.environ["SITE_DB"]) if os.environ.get("SITE_DB") else None)
    con = duckdb.connect(str(db), read_only=True) if db is not None else fixture_export(config.FIXTURE_DB)
    try:
        con.execute(f"COPY export_plays TO '{out}' (FORMAT parquet, COMPRESSION zstd)")
    finally:
        con.close()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, help="Parquet path (default: stdout)")
    args = ap.parse_args(argv)
    if args.out:
        write_parquet(args.out)
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "plays_explorer.parquet"
        write_parquet(path)
        with path.open("rb") as f:
            shutil.copyfileobj(f, sys.stdout.buffer)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
