"""Shared test helpers. Tests never print raw rows; assertions report counts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from pipeline import config


@pytest.fixture(scope="session")
def fixture_db_path() -> Path:
    """dev_fixtures.duckdb for THIS checkout, generated on first use."""
    if not config.FIXTURE_DB.exists() or not any(config.FIXTURE_RAW_DIR.glob("*.csv")):
        subprocess.run([sys.executable, str(config.REPO_ROOT / "scripts" / "make_fixtures.py")], check=True)
    return config.FIXTURE_DB


@pytest.fixture(scope="session")
def fx(fixture_db_path: Path) -> duckdb.DuckDBPyConnection:
    """Read-only connection to the expected-output fixture."""
    con = duckdb.connect(str(fixture_db_path), read_only=True)
    yield con
    con.close()

