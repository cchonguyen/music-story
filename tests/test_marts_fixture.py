"""W9c acceptance: mart_genre_xray (4-tuple uniqueness & explorer LEFT JOIN conservation),
mart_genre_hierarchy, and mart_genre_clock (local-time started_at_local alignment)."""

import pytest
from helpers import scalar
from mart_helpers import columns, diff_count

from pipeline.site_data import fixture_marts


@pytest.fixture(scope="module")
def con(fixture_db_path):
    return fixture_marts(fixture_db_path)


def test_w9c_mart_columns(con):
    assert columns(con, "mart_genre_xray") == [
        "track_id",
        "title",
        "artist",
        "artist_norm",
        "title_norm",
        "parent_genre",
        "style",
        "primary_weight",
        "level",
        "secondary_styles",
        "suppressed_umbrellas",
        "plays",
        "listen_hours",
        "skip_rate",
        "peak_local_hour",
        "top_country",
        "first_year",
        "last_year",
    ]
    assert columns(con, "mart_genre_hierarchy") == [
        "parent_genre",
        "style",
        "artist_id",
        "artist",
        "plays",
        "plays_weighted",
        "listen_hours",
        "tracks",
        "style_share_of_parent",
        "artist_share_of_style",
        "artist_rank_in_style",
    ]
    assert columns(con, "mart_genre_clock") == [
        "parent_genre",
        "style",
        "weekday_type",
        "hour",
        "plays",
        "plays_weighted",
        "listen_hours",
    ]


def test_genre_xray_unique_on_4tuple_key(con):
    total, distinct_4tuple = con.execute(
        """
        SELECT count(*),
               count(DISTINCT (artist_norm, title_norm, parent_genre, style))
        FROM mart_genre_xray
        """
    ).fetchone()
    assert total > 0
    assert total == distinct_4tuple


def test_explorer_left_join_xray_conserves_rows_and_matches_genre(con):
    pre_rows, post_rows, unmatched_classified = con.execute(
        """
        WITH joined AS (
            SELECT e.day,
                   e.artist_norm,
                   e.title_norm,
                   e.parent_genre,
                   e.style,
                   e.is_skip,
                   x.primary_weight,
                   x.level
            FROM explorer_plays e
            LEFT JOIN mart_genre_xray x
              USING (artist_norm, title_norm, parent_genre, style)
        )
        SELECT (SELECT count(*) FROM explorer_plays) AS pre_rows,
               count(*) AS post_rows,
               count(*) FILTER (
                   WHERE parent_genre IS NOT NULL AND primary_weight IS NULL
               ) AS unmatched_classified
        FROM joined
        """
    ).fetchone()
    assert pre_rows == post_rows
    assert unmatched_classified == 0


def test_genre_clock_uses_started_at_local(con):
    want = """
        SELECT g.parent_genre,
               g.style,
               hour(p.started_at_local) AS hour,
               count(*) AS plays
        FROM plays p
        JOIN track_genre g USING (track_id)
        GROUP BY 1, 2, 3
    """
    got = """
        SELECT parent_genre, style, hour, plays
        FROM mart_genre_clock
        WHERE weekday_type = 'all'
    """
    assert diff_count(con, got, want) == 0
    assert scalar(
        con,
        "SELECT min(hour) >= 0 AND max(hour) <= 23 FROM mart_genre_clock",
    )
