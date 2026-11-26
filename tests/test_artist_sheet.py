"""W14 / S1: artist genre sheet (pipeline/artist_sheet.py), on the fixture. Every file lives in tmp_path."""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import fresh_db, load_fx, scalar

from pipeline import artist_sheet as sheet

TABLES = [
    "dim_artist",
    "plays",
    "genre_map",
    "enr_lastfm_tags",
    "enr_spotify_artist",
    "enr_mb_artist",
    "enr_artist_genre_llm",
    "enr_discogs_artist",
]


@pytest.fixture
def con(fixture_db_path):
    con = fresh_db()
    load_fx(con, fixture_db_path, TABLES)
    # The fixture maps one genre per artist. Add every other mapped genre as a light Last.fm artist tag
    # (in this in-memory copy only) so the multi-genre paths get exercised: shares, overrides, no floor.
    con.execute(
        """
        INSERT INTO enr_lastfm_tags
        SELECT 'artist', d.artist_norm, m.tag, 25, TIMESTAMP '2026-01-01 00:00:00'
        FROM dim_artist d CROSS JOIN genre_map m
        WHERE m.is_genre AND NOT EXISTS (
            SELECT 1 FROM enr_lastfm_tags x
            WHERE x.entity_type = 'artist' AND x.entity_key = d.artist_norm AND x.tag = m.tag
        )
        """
    )
    yield con
    con.close()


@pytest.fixture
def base_rows(con):
    return sheet.rows(con)


def _group(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["artist_key"], []).append(r)
    return out


def _multi_genre_artist(rows: list[dict]) -> str:
    """First artist (by key) with at least two genres, so a share edit changes the normalised set."""
    counts: dict[str, int] = {}
    for r in rows:
        if r["style"] is not None:
            counts[r["artist_key"]] = counts.get(r["artist_key"], 0) + 1
    return next(k for k in sorted(counts) if counts[k] >= 2)


def _import(con, tmp_path: Path, rows_in: list[dict]) -> dict:
    path = tmp_path / "edited.csv"
    path.write_text(sheet.to_csv(rows_in), encoding="utf-8")
    return sheet.import_sheet(con, path, overrides_path=tmp_path / "ov.csv")


def test_rows_keep_only_artists_with_three_plays(con, base_rows):
    keys = {r["artist_key"] for r in base_rows}
    expected = scalar(
        con,
        "SELECT count(*) FROM dim_artist d JOIN (SELECT artist_id FROM plays GROUP BY 1 HAVING count(*) >= 3) p "
        "USING (artist_id)",
    )
    assert len(keys) == expected
    assert all(r["plays"] >= sheet.MIN_PLAYS for r in base_rows)
    assert all(r["source"] == "derived" for r in base_rows)


def test_shares_sum_to_one_per_artist(base_rows):
    for group in _group(base_rows).values():
        shares = [r["share"] for r in group if r["share"] is not None]
        if shares:
            assert abs(sum(shares) - 1) < 1e-3
        else:
            assert len(group) == 1


def test_no_share_floor(base_rows):
    small = [r for r in base_rows if r["share"] is not None and r["share"] < 0.15]
    assert small, "fixture has genres below 15 percent share; none may be dropped"


def test_csv_round_trip_keeps_artist_keys(base_rows):
    text = sheet.to_csv(base_rows)
    assert text.splitlines()[0] == ",".join(sheet.EXPORT_HEADER)
    back = sheet.parse_csv(text)
    assert len(back) == len(base_rows)
    assert {r["artist_key"] for r in back} == {r["artist_key"] for r in base_rows}


def test_parse_requires_columns():
    with pytest.raises(ValueError):
        sheet.parse_csv("artist_key,artist\nx,y\n")


def test_unedited_export_validates_clean(con, base_rows):
    groups = _group(sheet.parse_csv(sheet.to_csv(base_rows)))
    assert sheet.validate(groups, con) == []


def test_edited_share_becomes_manual_override(con, base_rows, tmp_path):
    key = _multi_genre_artist(base_rows)
    original = [r for r in base_rows if r["artist_key"] == key]
    total = sum(r["share"] for r in original if r["share"] is not None)
    edited = [dict(r) for r in base_rows]
    target = next(r for r in edited if r["artist_key"] == key)
    s0 = target["share"]
    target["share"] = s0 * 2

    report = _import(con, tmp_path, edited)
    assert report["errors"] == []
    assert report["changed"] == [key]
    assert report["reverted"] == []

    after = _group(sheet.rows(con))
    assert {r["source"] for r in after[key]} == {"manual"}
    assert all(r["source"] == "derived" for k, grp in after.items() if k != key for r in grp)
    got = next(r for r in after[key] if r["style"] == target["style"])["share"]
    expected = round(2 * s0 / (total + s0), 4)
    assert abs(got - expected) < 1e-3
    assert sheet.load_overrides(con, tmp_path / "ov.csv") == len(original)


def test_reimport_is_a_no_op(con, base_rows, tmp_path):
    keys = {r["artist_key"] for r in base_rows}
    original = list(base_rows)
    first = _import(con, tmp_path, original)
    assert first["errors"] == [] and first["changed"] == [] and first["reverted"] == []
    assert first["unchanged_count"] == len(keys)
    assert sheet.load_overrides(con, tmp_path / "ov.csv") == 0

    key = _multi_genre_artist(base_rows)
    edited = [dict(r) for r in base_rows]
    next(r for r in edited if r["artist_key"] == key)["share"] *= 2
    assert _import(con, tmp_path, edited)["changed"] == [key]
    count = sheet.load_overrides(con, tmp_path / "ov.csv")
    again = _import(con, tmp_path, edited)
    assert again["changed"] == [key] and again["reverted"] == []
    assert sheet.load_overrides(con, tmp_path / "ov.csv") == count

    back = _import(con, tmp_path, original)
    assert back["reverted"] == [key] and back["changed"] == []
    assert sheet.load_overrides(con, tmp_path / "ov.csv") == 0


def test_unknown_artist_key_writes_nothing(con, base_rows, tmp_path):
    bad = [dict(r) for r in base_rows] + [dict(base_rows[0], artist_key="no-such-artist-key")]
    report = _import(con, tmp_path, bad)
    assert any("unknown artist_key" in e for e in report["errors"])
    assert report["changed"] == []
    assert not (tmp_path / "ov.csv").exists()


def test_unknown_style_writes_nothing(con, base_rows, tmp_path):
    edited = [dict(r) for r in base_rows]
    next(r for r in edited if r["share"] is not None)["style"] = "not-a-real-style"
    report = _import(con, tmp_path, edited)
    assert any("is not a genre" in e for e in report["errors"])
    assert not (tmp_path / "ov.csv").exists()


def test_negative_share_writes_nothing(con, base_rows, tmp_path):
    edited = [dict(r) for r in base_rows]
    next(r for r in edited if r["share"] is not None)["share"] = -0.5
    report = _import(con, tmp_path, edited)
    assert any("positive number" in e for e in report["errors"])
    assert not (tmp_path / "ov.csv").exists()


def test_duplicate_style_writes_nothing(con, base_rows, tmp_path):
    edited = [dict(r) for r in base_rows]
    first = next(r for r in edited if r["share"] is not None)
    edited.append(dict(first))
    report = _import(con, tmp_path, edited)
    assert any("duplicate style" in e for e in report["errors"])
    assert not (tmp_path / "ov.csv").exists()


def test_blank_style_alone_clears_artist(con, base_rows, tmp_path):
    key = _multi_genre_artist(base_rows)
    name = next(r["artist"] for r in base_rows if r["artist_key"] == key)
    plays = next(r["plays"] for r in base_rows if r["artist_key"] == key)
    edited = [dict(r) for r in base_rows if r["artist_key"] != key]
    edited.append(
        {
            "artist_key": key,
            "artist": name,
            "plays": plays,
            "parent_genre": None,
            "style": None,
            "share": None,
            "source": "manual",
        }
    )
    report = _import(con, tmp_path, edited)
    assert report["errors"] == []
    assert report["changed"] == [key]
    after = _group(sheet.rows(con))[key]
    assert len(after) == 1
    assert after[0]["style"] is None and after[0]["parent_genre"] is None and after[0]["share"] is None
    assert after[0]["source"] == "manual"
