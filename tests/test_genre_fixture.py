"""W9 acceptance: pipeline/genre.py loads data/genre_map.csv and builds
track_genre from tags at track, album and artist level on the fixture.
Skipped until pipeline/genre.py exists."""

import pytest
from helpers import agreement, fresh_db, load_fx, scalar

genre = pytest.importorskip("pipeline.genre", reason="W9 not built yet")

INPUTS = ["dim_artist", "dim_album", "dim_track", "bridge_track_artist", "enr_spotify_track", "enr_spotify_artist",
          "enr_mb_recording", "enr_mb_artist", "enr_lastfm_tags"]


@pytest.fixture(scope="module")
def con(fixture_db_path):
    con = fresh_db()
    load_fx(con, fixture_db_path, INPUTS)
    genre.run(con)
    return con


def test_genre_map_covers_fixture_tags(con):
    missing = scalar(con, """SELECT count(*) FROM fx.genre_map f LEFT JOIN genre_map g USING (tag)
                             WHERE g.tag IS NULL OR g.is_genre <> f.is_genre
                                OR (f.is_genre AND (g.style <> f.style OR g.parent_genre <> f.parent_genre))""")
    assert missing == 0
    assert scalar(con, "SELECT count(*) FROM genre_map") >= 100        # a real starter map, not just the fixture's
    assert scalar(con, "SELECT count(*) FROM genre_map WHERE tag <> lower(trim(tag))") == 0
    assert scalar(con, "SELECT count(*) FROM genre_map WHERE is_genre AND (style IS NULL OR parent_genre IS NULL)") == 0


def test_weights(con):
    assert scalar(con, "SELECT max(abs(s - 1)) FROM (SELECT sum(weight) s FROM track_genre GROUP BY track_id)") < 1e-9
    assert scalar(con, "SELECT count(*) FROM track_genre WHERE weight <= 0 OR level NOT IN ('track', 'album', 'artist')") == 0
    assert scalar(con, """SELECT count(*) FROM track_genre t ANTI JOIN genre_map g
                          ON g.is_genre AND g.style = t.style AND g.parent_genre = t.parent_genre""") == 0


def test_top_style_matches_fixture(con):
    top = "SELECT track_id, arg_max(style, weight) s, arg_max(parent_genre, weight) p FROM {p}track_genre GROUP BY 1"
    on = f"FROM ({top.format(p='')}) g JOIN ({top.format(p='fx.')}) f USING (track_id)"
    assert scalar(con, f"SELECT count(*) {on}") >= 0.99 * scalar(con, "SELECT count(*) FROM fx.dim_track")
    assert agreement(con, f"SELECT g.s = f.s AND g.p = f.p {on}") >= 0.99


def test_noise_tags_never_count(con):
    assert scalar(con, "SELECT count(*) FROM track_genre WHERE style IN ('seen live', 'favorites') "
                       "OR regexp_matches(style, '^[0-9]{4}s?$')") == 0


def test_umbrella_style_disaggregates_to_substyles(fixture_db_path):
    c = fresh_db()
    load_fx(c, fixture_db_path, INPUTS)
    tid, a_norm, full_norm = c.execute(
        "SELECT t.track_id, t.artist_norm, t.full_norm FROM dim_track t LIMIT 1"
    ).fetchone()
    c.execute("DELETE FROM enr_lastfm_tags WHERE entity_key = ? OR entity_key = ?", [a_norm, f"{a_norm}::{full_norm}"])
    c.execute("DELETE FROM enr_spotify_artist")
    c.execute("DELETE FROM enr_mb_artist")
    c.execute("DELETE FROM enr_mb_recording")
    # Track has a heavy umbrella 'electronic' tag (100) alongside specific 'deep house' (60)
    c.executemany(
        "INSERT INTO enr_lastfm_tags VALUES (?, ?, ?, ?, TIMESTAMP '2026-10-22 00:00:00')",
        [("track", f"{a_norm}::{full_norm}", "electronic", 100),
         ("track", f"{a_norm}::{full_norm}", "deep house", 60)],
    )
    genre.run(c)
    rows = c.execute("SELECT parent_genre, style, weight, level FROM track_genre WHERE track_id = ?", [tid]).fetchall()
    assert rows == [("electronic", "deep house", 1.0, "track")]

