import json
import subprocess
import sys

import duckdb

from pipeline import config
from pipeline.site_data import mart_rows

YEAR_COLS = ["year", "plays", "skips", "listen_hours", "artists", "tracks", "new_artists", "new_tracks",
             "sessions"]


def test_year_rows_on_fixture(fixture_db_path):
    rows = mart_rows("year")
    assert len(rows) == 20
    assert list(rows[0]) == YEAR_COLS


def test_cli_prints_json(fixture_db_path):
    out = subprocess.run([sys.executable, "-m", "pipeline.site_data", "year"], cwd=config.REPO_ROOT,
                         capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    assert len(data) == 20 and set(data[0]) == set(YEAR_COLS)


def test_site_db_env_is_honoured(tmp_path, monkeypatch):
    db = tmp_path / "small.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE mart_year AS SELECT 2001 AS year, 5 AS plays")
    con.close()
    monkeypatch.setenv("SITE_DB", str(db))
    assert mart_rows("year") == [{"year": 2001, "plays": 5}]


def test_site_filters_trim_large_marts(fixture_db_path):
    assert max(r["rank"] for r in mart_rows("track_year")) == 50
    assert min(r["window_plays"] for r in mart_rows("binge")) >= 15
