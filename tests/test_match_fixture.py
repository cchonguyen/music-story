"""W2 acceptance on the full fixture: precision and recall of match_links
against the fixture's expected links, and the Gate 1 share. Skipped until
pipeline/match.py exists."""

import pytest
from helpers import fresh_db, scalar

match = pytest.importorskip("pipeline.match", reason="W2 not built yet")


@pytest.fixture(scope="module")
def matched(fixture_db_path):
    con = fresh_db()
    con.execute(f"ATTACH '{fixture_db_path}' AS fx (READ_ONLY)")
    con.execute("INSERT INTO stg_spotify SELECT * REPLACE (NULL AS artist_norm, NULL AS full_norm, "
                "NULL AS base_norm, NULL AS mix_desc) FROM fx.stg_spotify")
    con.execute("INSERT INTO stg_lastfm SELECT * REPLACE (NULL AS artist_norm, NULL AS full_norm, "
                "NULL AS base_norm, NULL AS mix_desc) FROM fx.stg_lastfm")
    match.run(con)
    return con


def test_precision_and_recall(matched):
    tp = scalar(matched, "SELECT count(*) FROM match_links JOIN fx.match_links USING (sp_id, lfm_id)")
    got = scalar(matched, "SELECT count(*) FROM match_links")
    want = scalar(matched, "SELECT count(*) FROM fx.match_links")
    assert tp / got >= 0.99, f"precision {tp / got:.4f}"
    assert tp / want >= 0.98, f"recall {tp / want:.4f}"


def test_gate1_share(matched):
    share = scalar(matched, """SELECT avg((m.lfm_id IS NOT NULL)::INT) FROM stg_lastfm l
                               LEFT JOIN match_links m USING (lfm_id)
                               WHERE year(l.scrobbled_at_utc) BETWEEN 2023 AND 2026""")
    assert share >= 0.95


def test_every_row_becomes_one_event(matched):
    sp = scalar(matched, "SELECT count(*) FROM stg_spotify")
    lf = scalar(matched, "SELECT count(*) FROM stg_lastfm")
    links = scalar(matched, "SELECT count(*) FROM match_links")
    assert scalar(matched, "SELECT count(*) FROM events") == sp + lf - links


def test_norm_columns_filled(matched):
    assert scalar(matched, "SELECT count(*) FROM stg_spotify WHERE full_norm IS NULL") == 0
    assert scalar(matched, "SELECT count(*) FROM stg_lastfm WHERE full_norm IS NULL") == 0
