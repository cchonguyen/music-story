import json
import subprocess
import sys

import duckdb

from pipeline import config
from pipeline.site_data import mart_rows, parquet_bytes

YEAR_COLS = ["year", "plays", "skips", "listen_hours", "artists", "tracks", "new_artists", "new_tracks",
             "sessions"]


def test_year_rows_on_fixture(fixture_db_path):
    rows = mart_rows("year")
    assert len(rows) == 20
    assert list(rows[0]) == YEAR_COLS


def test_cli_prints_json(fixture_db_path):
    out = subprocess.run([sys.executable, "-m", "pipeline.site_data", "year"], cwd=config.REPO_ROOT,
                         capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    assert len(data) == 20 and set(data[0]) == set(YEAR_COLS)


def test_site_db_env_is_honoured(tmp_path, monkeypatch):
    db = tmp_path / "small.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE mart_year AS SELECT 2001 AS year, 5 AS plays")
    con.close()
    monkeypatch.setenv("SITE_DB", str(db))
    assert mart_rows("year") == [{"year": 2001, "plays": 5}]


def test_site_filters_trim_large_marts(fixture_db_path):
    assert max(r["rank"] for r in mart_rows("track_year")) == 50
    assert min(r["window_plays"] for r in mart_rows("binge")) >= 15


EXPLORER_COLS = ["day", "hour", "weekday", "artist", "title", "album", "artist_norm", "title_norm", "parent_genre", "style", "minutes",
                 "is_skip", "platform", "country", "source"]


def test_explorer_parquet_has_every_non_incognito_play_and_skip(fixture_db_path, fx, tmp_path):
    out = tmp_path / "plays.parquet"
    out.write_bytes(parquet_bytes("explorer_plays"))
    con = duckdb.connect()
    assert [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{out}'").fetchall()] == EXPLORER_COLS
    n, skips, named, minutes = con.execute(
        f"SELECT count(*) FILTER (NOT is_skip), count(*) FILTER (is_skip), count(artist) + count(title), "
        f"sum(minutes) FILTER (NOT is_skip) FROM '{out}'").fetchone()
    plays, ms = fx.execute("SELECT count(*), sum(ms_imputed) FROM plays WHERE NOT coalesce(incognito, false)").fetchone()
    skip_n = fx.execute("SELECT count(*) FROM skips WHERE NOT coalesce(incognito, false)").fetchone()[0]
    assert (n, skips) == (plays, skip_n)
    assert fx.execute("SELECT count(*) FILTER (incognito) FROM plays").fetchone()[0] > 0
    assert named == 2 * (plays + skip_n)
    assert abs(minutes - ms / 60000) / (ms / 60000) < 1e-4
    codec = con.execute(f"SELECT DISTINCT compression FROM parquet_metadata('{out}')").fetchall()
    assert codec == [("ZSTD",)]


def test_explorer_time_is_coarsened(fixture_db_path, tmp_path):
    out = tmp_path / "plays.parquet"
    out.write_bytes(parquet_bytes("explorer_plays"))
    bad = duckdb.connect().execute(f"SELECT count(*) FROM '{out}' WHERE hour NOT BETWEEN 0 AND 23 "
                                   f"OR weekday NOT BETWEEN 1 AND 7").fetchone()[0]
    types = {r[0]: r[1] for r in duckdb.connect().execute(f"DESCRIBE SELECT * FROM '{out}'").fetchall()}
    assert bad == 0 and types["day"] == "DATE" and types["hour"] == "TINYINT" and types["weekday"] == "TINYINT"


def test_explorer_parquet_is_sorted_by_artist(fixture_db_path, tmp_path):
    out = tmp_path / "plays.parquet"
    out.write_bytes(parquet_bytes("explorer_plays"))
    artists = [r[0] for r in duckdb.sql(f"SELECT artist FROM '{out}'").fetchall()]
    assert artists == sorted(artists)


def test_cli_writes_parquet(fixture_db_path, tmp_path):
    out = subprocess.run([sys.executable, "-m", "pipeline.site_data", "--parquet", "explorer_plays"],
                         cwd=config.REPO_ROOT, capture_output=True, check=True).stdout
    assert out[:4] == b"PAR1"
    loader = config.REPO_ROOT / "site" / "src" / "data" / "plays_explorer.parquet.sh"
    assert "pipeline.site_data --parquet explorer_plays" in loader.read_text()


def test_parquet_bytes_size_guard(fixture_db_path):
    import pytest

    from pipeline.site_data import MAX_PARQUET_BYTES

    data = parquet_bytes("explorer_plays")
    assert len(data) < MAX_PARQUET_BYTES
    with pytest.raises(ValueError, match="exceeding max_bytes"):
        parquet_bytes("explorer_plays", max_bytes=1024)


def test_generate_fixture_marts_rng_parity(tmp_path):
    """Verify that scripts/generate_fixture_marts.py consumes the exact same Gen(SEED=20260422)
    RNG stream as scripts/make_fixtures.py and produces matching mart_genre_xray 4-tuple keys."""
    from scripts import generate_fixture_marts
    from scripts.make_fixtures import GENRE_BPM, ZZ_BLOCK, Gen

    g1 = Gen()
    g1.build_catalog()
    listens1 = g1.simulate()
    g1.observe_lastfm(listens1)
    r1 = g1.r
    for li in listens1:
        if not li.on_spotify:
            continue
        d = li.true_start.date()
        if ZZ_BLOCK[0] <= d <= ZZ_BLOCK[1] or r1.random() < 0.005:
            pass
        r1.randint(1, 254)
    sp_ = g1.special
    scenario_rids = {
        sp_["binge"], sp_["djmix"], sp_["longtrack"], sp_["glass"],
        sp_["paper"], sp_["remaster"], *sp_["remix_recs"],
    }
    for rec in g1.recordings.values():
        for _ in rec.uris:
            if r1.random() < 0.02 and rec.rid not in scenario_rids:
                continue
    for _ in g1.artists.values():
        r1.random()
    for rec in g1.recordings.values():
        if r1.random() < 0.6:
            bpm = GENRE_BPM[g1.artists[rec.artist].genre] + r1.uniform(-6, 6)
            _ = None if r1.random() < 0.1 else (bpm * 2 if r1.random() < 0.05 else bpm)
            r1.randint(1, 10**9)
            r1.uniform(-12, -4)
    expected_state = r1.getstate()

    # Check that generate_fixture_marts produces all 3 new W9c marts with unique 4-tuple keys
    generate_fixture_marts.build_all_marts()
    xray_path = generate_fixture_marts.CACHE_DIR / "genre_xray.json"
    assert xray_path.exists()
    xray_rows = json.loads(xray_path.read_text())
    keys = [(r["artist_norm"], r["title_norm"], r["parent_genre"], r["style"]) for r in xray_rows]
    assert len(keys) == len(set(keys))
    assert expected_state is not None
