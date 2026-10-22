"""W5 acceptance: sql/marts/10_simple.sql over the fixture's expected tables.
Skipped until the file exists. Every check reports counts, never rows."""

import pytest
from helpers import scalar
from mart_helpers import columns, diff_count, mart_db

from pipeline import config

if not (config.SQL_DIR / "marts" / "10_simple.sql").exists():
    pytest.skip("W5 not built yet", allow_module_level=True)

Y = "year(started_at_local)"


@pytest.fixture(scope="module")
def con(fixture_db_path):
    return mart_db(fixture_db_path, "10_simple.sql")


def aid(con, norm):
    return scalar(con, "SELECT artist_id FROM dim_artist WHERE artist_norm = ?", [norm])


def test_columns(con):
    assert columns(con, "mart_year") == ["year", "plays", "skips", "listen_hours", "artists", "tracks",
                                         "new_artists", "new_tracks", "sessions"]
    assert columns(con, "mart_artist_year") == ["year", "artist_id", "plays", "listen_hours", "rank"]
    assert columns(con, "mart_track_year") == ["year", "track_id", "artist_id", "plays", "listen_hours", "rank"]
    assert columns(con, "mart_clock") == ["year", "weekday", "hour", "plays"]
    assert columns(con, "mart_genre_year") == ["year", "parent_genre", "style", "plays_weighted"]
    assert columns(con, "mart_platform_year") == ["year", "platform_family", "plays"]


def test_mart_year(con):
    want = f"""
        WITH first_a AS (SELECT artist_id, arg_min({Y}, started_at_utc) y FROM plays GROUP BY 1),
             first_t AS (SELECT track_id, arg_min({Y}, started_at_utc) y FROM plays GROUP BY 1)
        SELECT p.year, p.plays, coalesce(s.skips, 0), round(p.h, 6), p.artists, p.tracks,
               coalesce(na.n, 0), coalesce(nt.n, 0), coalesce(se.n, 0)
        FROM (SELECT {Y} AS year, count(*) plays, sum(ms_imputed) / 3.6e6 h, count(DISTINCT artist_id) artists,
                     count(DISTINCT track_id) tracks FROM plays GROUP BY 1) p
        LEFT JOIN (SELECT {Y} y, count(*) skips FROM skips GROUP BY 1) s ON s.y = p.year
        LEFT JOIN (SELECT y, count(*) n FROM first_a GROUP BY 1) na ON na.y = p.year
        LEFT JOIN (SELECT y, count(*) n FROM first_t GROUP BY 1) nt ON nt.y = p.year
        LEFT JOIN (SELECT {Y} y, count(*) n FROM sessions GROUP BY 1) se ON se.y = p.year"""
    got = """SELECT year, plays, skips, round(listen_hours, 6), artists, tracks, new_artists, new_tracks, sessions
             FROM mart_year"""
    assert diff_count(con, got, want) == 0
    assert scalar(con, "SELECT count(*) FROM mart_year") == 20  # 2007..2026, one row per year


def test_artist_and_track_year(con):
    want = f"""SELECT {Y}, artist_id, count(*), round(sum(ms_imputed) / 3.6e6, 6),
                      row_number() OVER (PARTITION BY {Y} ORDER BY count(*) DESC, sum(ms_imputed) DESC, artist_id)
               FROM plays GROUP BY 1, 2"""
    got = "SELECT year, artist_id, plays, round(listen_hours, 6), rank FROM mart_artist_year"
    assert diff_count(con, got, want) == 0
    want = f"""SELECT {Y}, p.track_id, any_value(t.primary_artist_id), count(*), round(sum(ms_imputed) / 3.6e6, 6),
                      row_number() OVER (PARTITION BY {Y} ORDER BY count(*) DESC, sum(ms_imputed) DESC, p.track_id)
               FROM plays p JOIN dim_track t USING (track_id) GROUP BY 1, 2"""
    got = "SELECT year, track_id, artist_id, plays, round(listen_hours, 6), rank FROM mart_track_year"
    assert diff_count(con, got, want) == 0


def test_scenarios_in_artist_year(con):
    staple, flash = aid(con, "mara lantern"), aid(con, "pax ember")
    assert scalar(con, "SELECT count(*) FROM mart_artist_year WHERE artist_id = ?", [staple]) == 20
    assert scalar(con, "SELECT list(year) FROM mart_artist_year WHERE artist_id = ?", [flash]) == [2013]


def test_clock(con):
    want = f"SELECT {Y}, isodow(started_at_local), hour(started_at_local), count(*) FROM plays GROUP BY 1, 2, 3"
    assert diff_count(con, "SELECT * FROM mart_clock", want) == 0
    assert scalar(con, "SELECT min(weekday) = 1 AND max(weekday) = 7 AND min(hour) = 0 AND max(hour) = 23 "
                       "FROM mart_clock")


def test_genre_year(con):
    want = f"""SELECT {Y}, g.parent_genre, g.style, round(sum(g.weight), 6)
               FROM plays p JOIN track_genre g USING (track_id) GROUP BY 1, 2, 3"""
    got = "SELECT year, parent_genre, style, round(plays_weighted, 6) FROM mart_genre_year"
    assert diff_count(con, got, want) == 0
    # weights sum to 1 per track, so each year's weighted plays equal its plays
    assert scalar(con, """SELECT max(abs(g.w - y.plays)) FROM (SELECT year, sum(plays_weighted) w FROM mart_genre_year
                          GROUP BY 1) g JOIN mart_year y USING (year)""") < 1e-6
    top2 = scalar(con, """SELECT list(style ORDER BY w DESC)[1:2] FROM (SELECT style, sum(plays_weighted) w
                          FROM mart_genre_year WHERE year >= 2020 GROUP BY 1)""")
    assert sorted(top2) == ["house", "techno"]


def test_platform_year(con):
    want = f"SELECT {Y}, coalesce(platform_family, 'unknown'), count(*) FROM plays GROUP BY 1, 2"
    assert diff_count(con, "SELECT * FROM mart_platform_year", want) == 0
