"""Artist genre export for Concert Tracker, on the fixture."""

import json

import pytest
from helpers import fresh_db, load_fx, scalar

from pipeline import artist_genre, genre

INPUTS = ["dim_artist", "enr_spotify_artist", "enr_mb_artist", "enr_lastfm_tags"]


@pytest.fixture(scope="module")
def con(fixture_db_path):
    con = fresh_db()
    load_fx(con, fixture_db_path, INPUTS)
    con.execute(genre.LOAD_SQL)
    return con


@pytest.fixture(scope="module")
def artists(con):
    return artist_genre.artist_genres(con)


def test_some_artists_have_genres(con, artists):
    assert len(artists) >= 0.5 * scalar(con, "SELECT count(*) FROM dim_artist")
    assert len({a["artist_norm"] for a in artists}) == len(artists)


def test_weights_sum_to_one_and_respect_threshold(artists):
    for a in artists:
        total = sum(g["weight"] for g in a["genres"])
        assert abs(total - 1) < 1e-3
        assert all(g["weight"] > 0 for g in a["genres"])
        assert a["genres"] == sorted(a["genres"], key=lambda g: -g["weight"])
        assert set(a["inputs"]) <= {"lastfm", "spotify", "musicbrainz"} and a["inputs"]


def test_only_mapped_genres(con, artists):
    mapped = {(s, p) for s, p in con.execute("SELECT style, parent_genre FROM genre_map WHERE is_genre").fetchall()}
    for a in artists:
        for g in a["genres"]:
            assert (g["style"], g["parent"]) in mapped
            assert g["style"] not in ("seen live", "favorites")


def test_mbid_carried(con, artists):
    with_mbid = scalar(con, """SELECT count(*) FROM dim_artist WHERE artist_mbid IS NOT NULL
                               AND artist_norm IN (SELECT unnest(?::VARCHAR[]))""",
                       [[a["artist_norm"] for a in artists]])
    assert sum(1 for a in artists if a["mbid"]) == with_mbid


def test_export_file(con, tmp_path):
    out = tmp_path / "artist_genres.json"
    doc = artist_genre.export(con, out)
    back = json.loads(out.read_text())
    assert back["format"] == "music-story/artist-genres" and back["version"] == 1
    assert len(back["artists"]) == len(doc["artists"])
    assert back["genre_map"] and all(set(m) == {"tag", "style", "parent"} for m in back["genre_map"])
    assert all(m["style"] and m["parent"] for m in back["genre_map"])
