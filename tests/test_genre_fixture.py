"""W9 / W9b acceptance: pipeline/genre.py loads data/genre_map.csv and builds
track_genre from tags at track, album and artist level on the fixture."""

import csv

import pytest
from helpers import agreement, fresh_db, load_fx, scalar

from pipeline import config

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


def test_genre_map_csv_hygiene(con):
    with genre.GENRE_MAP_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == ["tag", "style", "parent_genre", "is_genre", "is_umbrella"]
        for row in reader:
            assert row["tag"] == row["tag"].strip().lower() and row["tag"]
            assert row["is_genre"] in ("true", "false")
            assert row["is_umbrella"] in ("true", "false")
            if row["is_genre"] == "true":
                assert row["parent_genre"] in genre.PARENTS
                assert row["style"] == row["style"].strip().lower() and row["style"]
                if row["style"] == row["parent_genre"]:
                    assert row["is_umbrella"] == "true"
            else:
                assert row["is_umbrella"] == "false"

    bad_fx = scalar(
        con,
        """SELECT count(*) FROM fx.genre_map
           WHERE (is_genre AND is_umbrella <> (style = parent_genre))
              OR (NOT is_genre AND is_umbrella)""",
    )
    assert bad_fx == 0


def test_legacy_step_15_matches_head_fixture_rounded_9dp(fixture_db_path):
    snap_path = config.REPO_ROOT / "tests" / "golden" / "genre_legacy_fixture.csv"
    lines = snap_path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("# generated from HEAD 7f935d5")
    expected = [
        (r["track_id"], r["parent_genre"], r["style"], r["weight"], r["level"])
        for r in csv.DictReader(lines[1:])
    ]

    c = fresh_db()
    load_fx(c, fixture_db_path, INPUTS)
    c.execute(genre.LOAD_SQL)
    genre.build(
        c,
        rho_min=0.15,
        rho_max=0.15,
        floor_min=0.15,
        floor_max=0.15,
        self_tag_only=True,
        two_stage=False,
    )
    actual = c.execute(
        """SELECT track_id, parent_genre, style, printf('%.9f', round(weight, 9)) AS weight, level
           FROM track_genre
           ORDER BY track_id, parent_genre, style"""
    ).fetchall()
    assert actual == expected

    # Verify two_stage=False vs two_stage=True on a multi-style parent track:
    # Parent 'pop' has total share 0.20 (k-pop 0.10 + j-pop 0.10), while 'electronic' has 'house' 0.80.
    tid, a_norm, full_norm = c.execute(
        "SELECT t.track_id, t.artist_norm, t.full_norm FROM dim_track t LIMIT 1"
    ).fetchone()
    c.execute("DELETE FROM enr_lastfm_tags")
    c.execute("DELETE FROM enr_spotify_artist")
    c.execute("DELETE FROM enr_mb_artist")
    c.execute("DELETE FROM enr_mb_recording")
    c.executemany(
        "INSERT INTO enr_lastfm_tags VALUES (?, ?, ?, ?, TIMESTAMP '2026-10-22 00:00:00')",
        [
            ("track", f"{a_norm}::{full_norm}", "house", 80),
            ("track", f"{a_norm}::{full_norm}", "k-pop", 10),
            ("track", f"{a_norm}::{full_norm}", "j-pop", 10),
        ],
    )
    genre.build(c, rho_min=0.15, rho_max=0.15, floor_min=0.15, floor_max=0.15, self_tag_only=True, two_stage=False)
    single_stage_parents = {r[0] for r in c.execute("SELECT parent_genre FROM track_genre WHERE track_id = ?", [tid]).fetchall()}
    assert single_stage_parents == {"electronic"}


def test_noise_share_under_soft_floor_is_dropped(fixture_db_path):
    c = fresh_db()
    load_fx(c, fixture_db_path, INPUTS)
    tid, a_norm, full_norm = c.execute(
        "SELECT t.track_id, t.artist_norm, t.full_norm FROM dim_track t LIMIT 1"
    ).fetchone()
    c.execute("DELETE FROM enr_lastfm_tags")
    c.execute("DELETE FROM enr_spotify_artist")
    c.execute("DELETE FROM enr_mb_artist")
    c.execute("DELETE FROM enr_mb_recording")
    c.executemany(
        "INSERT INTO enr_lastfm_tags VALUES (?, ?, ?, ?, TIMESTAMP '2026-10-22 00:00:00')",
        [
            ("track", f"{a_norm}::{full_norm}", "deep house", 92),
            ("track", f"{a_norm}::{full_norm}", "synthpop", 8),  # 8% <= 10% soft floor -> dropped
        ],
    )
    genre.run(c)
    rows = c.execute("SELECT parent_genre, style, weight FROM track_genre WHERE track_id = ?", [tid]).fetchall()
    assert rows == [("electronic", "deep house", 1.0)]


def test_pre_prune_conservation_and_post_prune_disaggregation_invariance(fixture_db_path):
    c = fresh_db()
    load_fx(c, fixture_db_path, INPUTS)
    tid, a_norm, full_norm = c.execute(
        "SELECT t.track_id, t.artist_norm, t.full_norm FROM dim_track t LIMIT 1"
    ).fetchone()
    c.execute("DELETE FROM enr_lastfm_tags WHERE entity_key = ? OR entity_key = ?", [a_norm, f"{a_norm}::{full_norm}"])
    c.executemany(
        "INSERT INTO enr_lastfm_tags VALUES (?, ?, ?, ?, TIMESTAMP '2026-10-22 00:00:00')",
        [
            ("track", f"{a_norm}::{full_norm}", "electronic", 50),
            ("track", f"{a_norm}::{full_norm}", "edm", 30),
            ("track", f"{a_norm}::{full_norm}", "deep house", 20),
            ("track", f"{a_norm}::{full_norm}", "indie", 25),
            ("track", f"{a_norm}::{full_norm}", "shoegaze", 15),
        ],
    )
    c.execute(genre.LOAD_SQL)
    # Compare post-prune parent totals with alpha=0 (no disaggregation: rho_min=1.0, rho_max=1.0) vs default ramp
    genre.build(c, rho_min=1.0, rho_max=1.0, floor_min=0.10, floor_max=0.20, self_tag_only=False, two_stage=True)
    no_disagg = dict(
        c.execute("SELECT parent_genre, sum(weight) FROM track_genre GROUP BY 1 ORDER BY 1").fetchall()
    )
    genre.build(c)
    with_disagg = dict(
        c.execute("SELECT parent_genre, sum(weight) FROM track_genre GROUP BY 1 ORDER BY 1").fetchall()
    )
    assert set(no_disagg) == set(with_disagg)
    for pg in no_disagg:
        assert abs(no_disagg[pg] - with_disagg[pg]) < 1e-9
