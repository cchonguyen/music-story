"""W1 acceptance: sql/01_ingest.sql on fixtures/raw reproduces the fixture's
raw, stg and lfm_self_dupes tables exactly. Skipped until the file exists."""

import pytest
from helpers import fresh_db, scalar

from pipeline import config

INGEST = config.SQL_DIR / "01_ingest.sql"
pytestmark = pytest.mark.skipif(not INGEST.exists(), reason="W1 not built yet")

COMPARE = {
    "raw_spotify": "*",
    "raw_lastfm": "*",
    "stg_spotify": "* EXCLUDE (artist_norm, full_norm, base_norm, mix_desc)",
    "stg_lastfm": "* EXCLUDE (artist_norm, full_norm, base_norm, mix_desc)",
    "lfm_self_dupes": "*",
}


@pytest.fixture(scope="module")
def ingested(fixture_db_path):
    con = fresh_db()
    con.execute("SET VARIABLE data_dir = ?", [str(config.FIXTURE_RAW_DIR)])
    con.execute(INGEST.read_text())
    con.execute(f"ATTACH '{fixture_db_path}' AS fx (READ_ONLY)")
    return con


@pytest.mark.parametrize("table", list(COMPARE))
def test_matches_fixture(ingested, table):
    cols = COMPARE[table]
    for a, b in (("memory", "fx"), ("fx", "memory")):
        diff = scalar(ingested, f"""SELECT count(*) FROM (
            SELECT {cols} FROM {a}.main.{table} EXCEPT ALL SELECT {cols} FROM {b}.main.{table})""")
        assert diff == 0, f"{table}: {diff} rows in {a} not in {b}"


def test_rerun_is_idempotent(ingested):
    before = scalar(ingested, "SELECT count(*) FROM memory.main.stg_spotify")
    ingested.execute("USE memory")
    ingested.execute(INGEST.read_text())
    assert scalar(ingested, "SELECT count(*) FROM memory.main.stg_spotify") == before
