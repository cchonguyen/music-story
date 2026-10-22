"""W6 acceptance: sql/marts/20_trap.sql over the fixture's expected tables.
These marts each have a tempting wrong answer; the fixture's named scenarios
catch it. Skipped until the file exists. Every check reports counts, never rows."""

import pytest
from helpers import scalar, scenario
from mart_helpers import columns, diff_count, mart_db

from pipeline import config

if not (config.SQL_DIR / "marts" / "20_trap.sql").exists():
    pytest.skip("W6 not built yet", allow_module_level=True)

Y = "year(started_at_local)"


@pytest.fixture(scope="module")
def con(fixture_db_path):
    return mart_db(fixture_db_path, "20_trap.sql")


def aid(con, norm):
    return scalar(con, "SELECT artist_id FROM dim_artist WHERE artist_norm = ?", [norm])


def arc(con, norm):
    return con.execute("""SELECT first_year, last_year, years_active, longest_gap_years, comeback_year, peak_year,
                                 round(peak_share, 4) FROM mart_artist_arc WHERE artist_id = ?""",
                       [aid(con, norm)]).fetchone()


def test_columns(con):
    assert columns(con, "mart_artist_arc") == ["artist_id", "plays", "first_year", "last_year", "years_active",
                                               "longest_gap_years", "comeback_year", "peak_year", "peak_share"]
    assert columns(con, "mart_binge") == ["track_id", "window_start", "window_plays", "lifetime_plays", "rate_ratio"]
    assert columns(con, "mart_remixer_year") == ["artist_id", "year", "remix_plays", "original_plays"]
    assert columns(con, "mart_song_age") == ["year", "age_bucket", "plays"]
    assert columns(con, "mart_skip_rate") == ["year", "skips", "spotify_plays", "skip_rate"]
    assert columns(con, "mart_sessions_year") == ["year", "sessions", "median_minutes", "p90_minutes",
                                                  "sessions_10", "sessions_30"]
    assert columns(con, "mart_country_year") == ["year", "country", "plays", "imputed_plays"]


def test_artist_arc_scenarios(con):
    staple, comeback, flash = arc(con, "mara lantern"), arc(con, "oslo wilder"), arc(con, "pax ember")
    assert staple[:5] == (2007, 2026, 20, 0, None)
    assert comeback[:5] == (2008, 2026, 15, 4, 2016)        # silent 2012-2015
    assert flash[:6] == (2013, 2013, 1, 0, None, 2013) and flash[6] == 1.0
    assert scalar(con, "SELECT count(*) FROM mart_artist_arc") == scalar(con, "SELECT count(DISTINCT artist_id) FROM plays")
    assert scalar(con, "SELECT sum(plays) FROM mart_artist_arc") == scalar(con, "SELECT count(*) FROM plays")


def test_artist_arc_gap_counts_missing_years_not_first_to_last(con):
    # A one-year gap is not a comeback; comeback_year needs a gap of >= 3 missing years.
    assert scalar(con, "SELECT count(*) FROM mart_artist_arc WHERE comeback_year IS NOT NULL AND longest_gap_years < 3") == 0
    assert scalar(con, "SELECT count(*) FROM mart_artist_arc WHERE years_active + longest_gap_years > "
                       "last_year - first_year + 1") == 0


def test_binge(con):
    track = scenario(con, "binge", "track_id")
    start, plays = con.execute("SELECT window_start, window_plays FROM mart_binge WHERE track_id = ?", [track]).fetchone()
    assert str(start) >= "2019-04-18" and str(start) <= "2019-05-12"   # a rolling 14-day window, local dates
    assert plays >= 24
    # only tracks with >= 10 plays; window_plays never exceeds lifetime plays
    assert scalar(con, "SELECT count(*) FROM mart_binge WHERE lifetime_plays < 10 OR window_plays > lifetime_plays") == 0
    want = "SELECT count(*) FROM (SELECT track_id FROM plays GROUP BY 1 HAVING count(*) >= 10)"
    assert scalar(con, "SELECT count(*) FROM mart_binge") == scalar(con, want)
    # the binge track stands out against its own average rate
    assert scalar(con, "SELECT rate_ratio FROM mart_binge WHERE track_id = ?", [track]) >= 5


def test_binge_window_is_rolling_and_maximal(con):
    want = """
        WITH d AS (SELECT track_id, started_at_local::DATE AS day FROM plays
                   WHERE track_id IN (SELECT track_id FROM plays GROUP BY 1 HAVING count(*) >= 10)),
             w AS (SELECT a.track_id, a.day AS window_start, count(*) AS n
                   FROM (SELECT DISTINCT track_id, day FROM d) a
                   JOIN d b ON b.track_id = a.track_id AND b.day >= a.day AND b.day < a.day + 14
                   GROUP BY 1, 2)
        SELECT track_id, arg_min(window_start, (-n, window_start)), max(n) FROM w GROUP BY 1"""
    assert diff_count(con, "SELECT track_id, window_start, window_plays FROM mart_binge", want) == 0


def test_remixer(con):
    rx = aid(con, scenario(con, "remixer", "artist_norm"))
    remix, orig = con.execute("""SELECT sum(remix_plays), sum(original_plays) FROM mart_remixer_year
                                 WHERE artist_id = ? AND year >= 2018""", [rx]).fetchone()
    assert remix > orig > 0
    # credited through bridge_track_artist role 'remixer', not as primary artist
    want = f"""SELECT b.artist_id, {Y}, count(*) FROM plays p JOIN bridge_track_artist b USING (track_id)
               WHERE b.role = 'remixer' GROUP BY 1, 2"""
    assert diff_count(con, "SELECT artist_id, year, remix_plays FROM mart_remixer_year WHERE remix_plays > 0", want) == 0


def test_song_age_uses_work_year(con):
    bucket = """CASE WHEN t.work_year IS NULL THEN 'unknown'
                     WHEN y - t.work_year <= 0 THEN '0' WHEN y - t.work_year <= 2 THEN '1-2'
                     WHEN y - t.work_year <= 5 THEN '3-5' WHEN y - t.work_year <= 10 THEN '6-10'
                     WHEN y - t.work_year <= 20 THEN '11-20' ELSE '21+' END"""
    want = f"""SELECT y, {bucket}, count(*) FROM (SELECT {Y} y, track_id FROM plays) p
               JOIN dim_track t USING (track_id) GROUP BY 1, 2"""
    assert diff_count(con, "SELECT * FROM mart_song_age", want) == 0


def test_skip_rate_excludes_lastfm_only(con):
    want = f"""SELECT p.y, coalesce(s.n, 0), p.n, round(coalesce(s.n, 0) / (coalesce(s.n, 0) + p.n), 6)
               FROM (SELECT {Y} y, count(*) n FROM plays WHERE source <> 'lastfm' GROUP BY 1) p
               LEFT JOIN (SELECT {Y} y, count(*) n FROM skips GROUP BY 1) s USING (y)
               WHERE p.y >= 2012"""
    got = "SELECT year, skips, spotify_plays, round(skip_rate, 6) FROM mart_skip_rate"
    assert diff_count(con, got, want) == 0


def test_sessions_year_uses_utc_durations(con):
    want = f"""SELECT s.y, s.n, round(s.med, 4), round(s.p90, 4), f.n10, f.n30
               FROM (SELECT {Y} y, count(*) n,
                            median(epoch(ended_at_utc - started_at_utc) / 60) med,
                            quantile_cont(epoch(ended_at_utc - started_at_utc) / 60, 0.9) p90
                     FROM sessions GROUP BY 1) s
               JOIN (SELECT y, sum(new_session_10::INT) n10, sum(new_session_30::INT) n30
                     FROM (SELECT {Y} y, new_session_10, new_session_30 FROM plays
                           UNION ALL SELECT {Y}, new_session_10, new_session_30 FROM skips) GROUP BY 1) f USING (y)"""
    got = """SELECT year, sessions, round(median_minutes, 4), round(p90_minutes, 4), sessions_10, sessions_30
             FROM mart_sessions_year"""
    assert diff_count(con, got, want) == 0


def test_country_year(con):
    want = f"""SELECT {Y}, coalesce(country, 'unknown'), count(*), count(*) FILTER (WHERE country_imputed)
               FROM plays GROUP BY 1, 2"""
    assert diff_count(con, "SELECT * FROM mart_country_year", want) == 0
    assert scalar(con, "SELECT plays FROM mart_country_year WHERE year = 2023 AND country = 'JP'") == 48
