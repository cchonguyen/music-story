"""W15: track genre sheet (pipeline/track_sheet.py), on the fixture. Every file lives in tmp_path."""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import fresh_db, load_fx, scalar

from pipeline import track_sheet as sheet

TABLES = ["dim_track", "dim_artist", "plays", "track_genre", "genre_map"]


@pytest.fixture
def con(fixture_db_path):
    con = fresh_db()
    load_fx(con, fixture_db_path, TABLES)
    yield con
    con.close()


def _valid_pair(con) -> tuple[str, str]:
    return con.execute(
        "SELECT parent_genre, style FROM genre_map WHERE is_genre AND style IS NOT NULL "
        "AND parent_genre IS NOT NULL AND NOT is_umbrella ORDER BY style LIMIT 1"
    ).fetchone()


def _busy_track(con) -> tuple[str, str]:
    """A track with at least 3 plays, and its primary artist_norm."""
    return con.execute(
        "SELECT t.track_id, t.artist_norm FROM dim_track t JOIN plays p ON p.track_id = t.track_id "
        "GROUP BY t.track_id, t.artist_norm HAVING count(*) >= 3 ORDER BY t.track_id LIMIT 1"
    ).fetchone()


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_export_only_lists_tracks_with_enough_plays(con):
    data = sheet.rows(con, 3)
    assert data, "fixture should have tracks with 3+ plays"
    assert all(r["plays"] >= 3 for r in data)
    assert sheet.to_csv(data).splitlines()[0] == ",".join(sheet.EXPORT_HEADER)


def test_track_edit_replaces_automatic_genres(con, tmp_path):
    track_id, _ = _busy_track(con)
    parent, style = _valid_pair(con)
    overrides = _write(
        tmp_path / "track_overrides.csv",
        "track_id,parent_genre,style,share\n" f"{track_id},{parent},{style},1\n",
    )
    sheet.apply(con, overrides)
    rows = con.execute(
        "SELECT parent_genre, style, level FROM track_genre WHERE track_id = ?", [track_id]
    ).fetchall()
    assert rows == [(parent, style, "manual")]


def test_artist_edit_carries_down_to_tracks(con, tmp_path):
    track_id, artist = _busy_track(con)
    parent, style = _valid_pair(con)
    artist_file = _write(
        tmp_path / "artist_overrides.csv",
        "artist_key,parent_genre,style,share\n" f"{artist},{parent},{style},1\n",
    )
    res = sheet.apply(
        con,
        tmp_path / "missing_track_overrides.csv",
        artist_overrides_path=artist_file,
    )
    rows = con.execute(
        "SELECT parent_genre, style, level FROM track_genre WHERE track_id = ?", [track_id]
    ).fetchall()
    assert rows == [(parent, style, "artist")]
    expected_carried = scalar(
        con, "SELECT count(*) FROM track_genre WHERE track_id IN (SELECT track_id FROM dim_track WHERE artist_norm = ?)",
        [artist],
    )
    assert res["artist_carried_rows"] == expected_carried


def test_blank_style_clears_a_track(con, tmp_path):
    track_id, _ = _busy_track(con)
    overrides = _write(
        tmp_path / "track_overrides.csv",
        "track_id,parent_genre,style,share\n" f"{track_id},,,\n",
    )
    sheet.apply(con, overrides)
    assert scalar(con, "SELECT count(*) FROM track_genre WHERE track_id = ?", [track_id]) == 0


def test_import_rejects_unknown_genre_and_writes_nothing(con, tmp_path):
    track_id, _ = _busy_track(con)
    sheet_file = _write(
        tmp_path / "sheet.csv",
        "track_id,title,artist,plays,parent_genre,style,share,source\n"
        f"{track_id},t,a,3,not-a-parent,not-a-style,1,auto\n",
    )
    target = tmp_path / "track_overrides.csv"
    report = sheet.import_sheet(con, sheet_file, overrides_path=target)
    assert report["errors"], "an unknown genre must be reported"
    assert not target.exists()


def test_site_rows_have_the_export_columns(con):
    data = sheet.rows(con, 3)
    assert data
    assert set(data[0].keys()) == {"track_id", "title", "artist", "plays", "parent_genre", "style", "share", "source"}


def test_zero_share_rows_are_ignored_and_same_style_under_two_parents_is_allowed(con):
    track_id, _ = _busy_track(con)
    parent, style = _valid_pair(con)
    group = [
        {"parent_genre": parent, "style": style, "share": "1"},
        {"parent_genre": parent, "style": style, "share": "0"},
    ]
    assert sheet.validate({track_id: group}, con) == []
    assert sheet.normalise(group) == [(parent, style, 1.0)]

    other_parent = con.execute(
        "SELECT DISTINCT parent_genre FROM genre_map WHERE is_genre AND parent_genre IS NOT NULL "
        "AND parent_genre <> ? ORDER BY parent_genre LIMIT 1",
        [parent],
    ).fetchone()[0]
    con.execute(
        "INSERT INTO genre_map VALUES (?, ?, ?, true, false)",
        [f"{style}_alt_test", style, other_parent],
    )
    two_parent_group = [
        {"parent_genre": parent, "style": style, "share": "0.5"},
        {"parent_genre": other_parent, "style": style, "share": "0.5"},
    ]
    assert sheet.validate({track_id: two_parent_group}, con) == []
    dup_same_parent = [
        {"parent_genre": parent, "style": style, "share": "0.5"},
        {"parent_genre": parent, "style": style, "share": "0.5"},
    ]
    assert sheet.validate({track_id: dup_same_parent}, con)


def test_unedited_export_with_zero_share_row_is_unchanged_on_dry_run(con, tmp_path):
    track_id, _ = _busy_track(con)
    pairs = con.execute(
        "SELECT parent_genre, style FROM genre_map WHERE is_genre AND style IS NOT NULL "
        "AND parent_genre IS NOT NULL AND NOT is_umbrella ORDER BY style LIMIT 2"
    ).fetchall()
    (p1, s1), (p2, s2) = pairs[0], pairs[1]
    con.execute("DELETE FROM track_genre WHERE track_id = ?", [track_id])
    con.execute("INSERT INTO track_genre VALUES (?, ?, ?, 1.0, 'track')", [track_id, p1, s1])
    con.execute("INSERT INTO track_genre VALUES (?, ?, ?, 1e-6, 'track')", [track_id, p2, s2])

    exported = sheet.rows(con, 3)
    sheet_file = _write(tmp_path / "sheet.csv", sheet.to_csv(exported))
    report = sheet.import_sheet(con, sheet_file, dry_run=True, overrides_path=tmp_path / "ov.csv")
    assert report["errors"] == []
    assert report["changed"] == []
    assert report["unchanged_count"] == len({r["track_id"] for r in exported})
