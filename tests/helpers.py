"""Helpers shared by tests. Import as `from helpers import ...`."""

from __future__ import annotations

import duckdb

from pipeline import config


def fresh_db() -> duckdb.DuckDBPyConnection:
    """An in-memory database with schema.sql applied."""
    con = duckdb.connect()
    con.execute(config.SCHEMA_SQL.read_text())
    return con


def scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None):
    return con.execute(sql, params or []).fetchone()[0]


def scenario(con: duckdb.DuckDBPyConnection, name: str, key: str) -> str:
    return scalar(con, "SELECT value FROM fixture_scenarios WHERE scenario = ? AND key = ?", [name, key])
