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


def load_fx(con: duckdb.DuckDBPyConnection, fixture_db_path, tables: list[str]) -> None:
    """Copy the fixture's expected tables into the schema tables of `con`, then keep the
    fixture attached read-only as `fx` for comparisons."""
    con.execute(f"ATTACH '{fixture_db_path}' AS fx (READ_ONLY)")
    for t in tables:
        con.execute(f"INSERT INTO {t} SELECT * FROM fx.{t}")
    con.execute("CREATE TABLE fixture_scenarios AS SELECT * FROM fx.fixture_scenarios")


def agreement(con: duckdb.DuckDBPyConnection, sql: str) -> float:
    """sql returns one boolean per compared row; the share that is true."""
    return scalar(con, f"SELECT avg(ok::INT) FROM ({sql}) t(ok)")
