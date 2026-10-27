"""W12 acceptance: export_plays passes the privacy gate and round-trips as Zstd Parquet."""

import subprocess
import sys

import duckdb
import pytest

from pipeline import config
from pipeline.export import fixture_export, write_parquet
from pipeline.site_data import fixture_marts
from tests.mart_helpers import columns

EXPORT_COLS = ["local_date", "year", "hour", "weekday", "artist", "track", "album", "parent_genre", "style",
               "release_year", "seconds", "source", "platform", "country", "shuffle"]


@pytest.fixture(scope="module")
def con(fixture_db_path):
    c = fixture_export(fixture_db_path)
    yield c
    c.close()


def one(con, sql):
    return con.execute(sql).fetchone()[0]


def test_columns(con):
    assert columns(con, "export_plays") == EXPORT_COLS


def test_incognito_dropped(con):
    assert one(con, "SELECT count(*) FILTER (incognito) FROM plays") > 0
    assert one(con, "SELECT count(*) FROM export_plays") == one(
        con, "SELECT count(*) FROM plays WHERE NOT coalesce(incognito, false)")


def test_no_timestamps_or_ids(con):
    types = {r[1] for r in con.execute("DESCRIBE export_plays").fetchall()}
    assert not any("TIMESTAMP" in t or t == "TIME" for t in types)
    assert not any(c.endswith(("_id", "_utc")) for c in EXPORT_COLS)


def test_time_parts_match_local_time(con):
    assert one(con, "SELECT count(*) FROM export_plays WHERE hour NOT BETWEEN 0 AND 23 "
                    "OR weekday NOT BETWEEN 1 AND 7 OR year <> year(local_date)") == 0
    got = "SELECT local_date, hour, weekday, count(*) FROM export_plays GROUP BY ALL"
    want = """SELECT CAST(started_at_local AS DATE), hour(started_at_local), isodow(started_at_local), count(*)
              FROM plays WHERE NOT coalesce(incognito, false) GROUP BY ALL"""
    assert one(con, f"SELECT count(*) FROM (({got}) EXCEPT ({want}))") == 0


def test_every_row_has_names_and_seconds(con):
    assert one(con, "SELECT count(*) FROM export_plays WHERE artist IS NULL OR track IS NULL "
                    "OR seconds IS NULL OR seconds < 0") == 0
    assert one(con, "SELECT sum(seconds) FROM export_plays") == pytest.approx(one(
        con, "SELECT sum(ms_imputed) / 1000 FROM plays WHERE NOT coalesce(incognito, false)"), rel=1e-4)


def test_genre_is_top_weight(con):
    bad = one(con, """
        WITH top AS (SELECT track_id, max(weight) AS w FROM track_genre GROUP BY 1)
        SELECT count(*) FROM (SELECT DISTINCT p.track_id, e.parent_genre, e.style
            FROM plays p JOIN dim_track t USING (track_id) JOIN dim_artist a ON a.artist_id = p.artist_id
            JOIN export_plays e ON e.track = t.title AND e.artist = a.name
            JOIN top USING (track_id)) x
        WHERE NOT EXISTS (SELECT 1 FROM track_genre g JOIN top USING (track_id)
                          WHERE g.track_id = x.track_id AND g.weight = top.w
                            AND g.parent_genre = x.parent_genre AND g.style = x.style)""")
    assert bad == 0


def test_parquet_roundtrip(fixture_db_path, tmp_path, con):
    out = tmp_path / "plays_explorer.parquet"
    write_parquet(out)
    r = duckdb.connect()
    assert r.execute(f"SELECT count(*) FROM '{out}'").fetchone()[0] == one(con, "SELECT count(*) FROM export_plays")
    assert {c[0] for c in r.execute(f"SELECT DISTINCT compression FROM parquet_metadata('{out}')").fetchall()} \
        == {"ZSTD"}


def test_site_db_env_is_honoured(tmp_path, monkeypatch):
    db = tmp_path / "small.duckdb"
    c = duckdb.connect(str(db))
    c.execute("CREATE TABLE export_plays AS SELECT DATE '2001-01-01' AS local_date, 'a' AS artist")
    c.close()
    monkeypatch.setenv("SITE_DB", str(db))
    out = tmp_path / "x.parquet"
    write_parquet(out)
    assert duckdb.connect().execute(f"SELECT count(*), any_value(artist) FROM '{out}'").fetchone() == (1, "a")


def test_cli_writes_parquet_to_stdout(fixture_db_path):
    out = subprocess.run([sys.executable, "-m", "pipeline.export"], cwd=config.REPO_ROOT,
                         capture_output=True, check=True).stdout
    assert out[:4] == b"PAR1" and out[-4:] == b"PAR1"


def test_loader_calls_export():
    loader = config.REPO_ROOT / "site" / "src" / "data" / "plays_explorer.parquet.sh"
    assert "pipeline.export" in loader.read_text()


def test_site_marts_carry_no_timestamps(fixture_db_path):
    c = fixture_marts(fixture_db_path)
    bad = c.execute("""SELECT table_name || '.' || column_name FROM information_schema.columns
                       WHERE table_name LIKE 'mart_%' AND (data_type LIKE 'TIMESTAMP%' OR data_type = 'TIME')
                       """).fetchall()
    c.close()
    assert bad == []
