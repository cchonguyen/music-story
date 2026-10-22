"""W8 acceptance: sql/05_sessions.sql builds plays, skips and sessions from the
fixture's events, staging and dimension tables. Columns that do not depend on
the Last.fm-only track lookup must match exactly; the rest within 1%
(track_key_map picks one recording per key, the fixture knows the true one).
Skipped until the file exists."""

import pytest
from helpers import agreement, fresh_db, load_fx, scalar

from pipeline import config

SQL = config.SQL_DIR / "05_sessions.sql"
if not SQL.exists():
    pytest.skip("W8 not built yet", allow_module_level=True)

INPUTS = ["stg_spotify", "events", "enr_spotify_track", "dim_artist", "dim_album", "dim_track", "bridge_track_artist",
          "track_uri_map", "track_key_map"]

EXACT = ["started_at_utc", "started_at_local", "tz", "country", "country_imputed", "source", "ms_played",
         "match_pass", "match_gap_sec", "platform_family", "shuffle", "offline", "incognito", "reason_start",
         "reason_end", "skipped"]
NEAR = ["ended_at_utc", "track_id", "artist_id", "album_id", "ms_imputed", "session_index", "new_session_10",
        "new_session_30"]


@pytest.fixture(scope="module")
def con(fixture_db_path):
    con = fresh_db()
    load_fx(con, fixture_db_path, INPUTS)
    con.execute("SET VARIABLE country_tz_csv = ?", [str(config.COUNTRY_TZ_CSV)])
    con.execute("SET VARIABLE repo_root = ?", [str(config.REPO_ROOT)])
    con.execute(SQL.read_text())
    return con


@pytest.mark.parametrize("table", ["plays", "skips"])
def test_same_rows(con, table):
    assert scalar(con, f"SELECT count(*) FROM {table}") == scalar(con, f"SELECT count(*) FROM fx.{table}")
    assert scalar(con, f"SELECT count(*) FROM {table} ANTI JOIN fx.{table} USING (play_id)") == 0


@pytest.mark.parametrize("table", ["plays", "skips"])
@pytest.mark.parametrize("col", EXACT)
def test_exact_columns(con, table, col):
    bad = scalar(con, f"SELECT count(*) FROM {table} p JOIN fx.{table} f USING (play_id) "
                      f"WHERE p.{col} IS DISTINCT FROM f.{col}")
    assert bad == 0, f"{table}.{col}: {bad} rows differ"


@pytest.mark.parametrize("table", ["plays", "skips"])
@pytest.mark.parametrize("col", NEAR)
def test_near_columns(con, table, col):
    share = agreement(con, f"SELECT p.{col} IS NOT DISTINCT FROM f.{col} FROM {table} p JOIN fx.{table} f USING (play_id)")
    assert share >= 0.99, f"{table}.{col}: {share:.4f}"


def test_completion_ratio(con):
    # exact for Spotify-backed rows; NULL for Last.fm-only rows and longform mixes
    bad = scalar(con, """SELECT count(*) FROM plays p JOIN fx.plays f USING (play_id) WHERE p.source <> 'lastfm'
                         AND ((p.completion_ratio IS NULL) <> (f.completion_ratio IS NULL)
                              OR abs(p.completion_ratio - f.completion_ratio) > 1e-9)""")
    assert bad == 0
    assert scalar(con, "SELECT count(*) FROM plays WHERE source = 'lastfm' AND completion_ratio IS NOT NULL") == 0


def test_session_ids_are_consistent(con):
    assert scalar(con, "SELECT count(*) FROM (SELECT play_id, session_id FROM plays UNION ALL "
                       "SELECT play_id, session_id FROM skips) x ANTI JOIN sessions USING (session_id)") == 0
    n, fx_n = scalar(con, "SELECT count(*) FROM sessions"), scalar(con, "SELECT count(*) FROM fx.sessions")
    assert abs(n - fx_n) <= 0.005 * fx_n, f"{n} sessions vs {fx_n}"
    # session totals agree with their rows
    assert scalar(con, """SELECT count(*) FROM sessions s JOIN (
                            SELECT session_id, count(*) FILTER (WHERE k = 'p') np, count(*) FILTER (WHERE k = 's') ns
                            FROM (SELECT session_id, 'p' k FROM plays UNION ALL SELECT session_id, 's' FROM skips)
                            GROUP BY 1) c USING (session_id)
                          WHERE s.n_plays <> c.np OR s.n_skips <> c.ns""") == 0


def test_session_attributes(con):
    on = "FROM sessions s JOIN fx.sessions f USING (started_at_utc)"
    assert scalar(con, f"SELECT count(*) {on}") >= 0.99 * scalar(con, "SELECT count(*) FROM fx.sessions")
    for col in ("started_at_local", "tz", "n_plays", "n_skips", "platform_family", "sources", "ended_at_utc"):
        share = agreement(con, f"SELECT s.{col} IS NOT DISTINCT FROM f.{col} {on}")
        assert share >= 0.99, f"sessions.{col}: {share:.4f}"
    # listen_ms sums every row, so one Last.fm-only play resolved to another recording of the same
    # key shifts the whole session: exact where every track agrees, >= 97% overall.
    clean = ("NOT EXISTS (SELECT 1 FROM plays p JOIN fx.plays q USING (play_id) "
             "WHERE p.session_id = s.session_id AND p.track_id <> q.track_id)")
    assert agreement(con, f"SELECT s.listen_ms = f.listen_ms {on} WHERE {clean}") == 1.0
    assert agreement(con, f"SELECT s.listen_ms = f.listen_ms {on}") >= 0.97


def test_dst_and_travel(con):
    # local time comes from the row's IANA zone, so the spring-forward hour does not exist in LA
    assert scalar(con, """SELECT count(*) FROM plays WHERE tz = 'America/Los_Angeles'
                          AND started_at_local::DATE = '2024-03-10' AND hour(started_at_local) = 2""") == 0
    assert scalar(con, "SELECT count(*) FROM plays WHERE country = 'JP' AND tz = 'Asia/Tokyo'") == \
        scalar(con, "SELECT count(*) FROM fx.plays WHERE country = 'JP'")
