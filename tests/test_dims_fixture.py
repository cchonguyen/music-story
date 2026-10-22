"""W7 acceptance: pipeline/dims.py builds the dimension and mapping tables from
events + enr_* on the fixture. Fixture ids are arbitrary, so artists and albums
are compared by natural key; tracks by track_id (the ISRC when one is known).
Thresholds leave room for what the enrichment data cannot recover (5 Spotify
URIs return 404 with no sibling URI; some Last.fm-only songs exist nowhere else).
Skipped until pipeline/dims.py exists."""

import pytest
from helpers import agreement, fresh_db, load_fx, scalar, scenario

dims = pytest.importorskip("pipeline.dims", reason="W7 not built yet")

INPUTS = ["events", "enr_local_duration", "enr_spotify_track", "enr_spotify_artist", "enr_mb_recording",
          "enr_mb_artist", "enr_lastfm_tags", "enr_lastfm_info", "enr_deezer_track"]

# every event resolved to a pipeline track_id, next to the fixture's answer
RESOLVED = """
    SELECT e.event_id, e.source, coalesce(u.track_id, k.track_id) AS got, f.track_id AS want
    FROM events e
    LEFT JOIN track_uri_map u ON u.track_uri = e.track_uri
    LEFT JOIN track_key_map k ON e.track_uri IS NULL AND k.artist_norm = e.artist_norm AND k.full_norm = e.full_norm
    JOIN (SELECT play_id, track_id FROM fx.plays UNION ALL SELECT play_id, track_id FROM fx.skips) f
      ON f.play_id = e.event_id"""


@pytest.fixture(scope="module")
def con(fixture_db_path):
    con = fresh_db()
    load_fx(con, fixture_db_path, INPUTS)
    dims.run(con)
    return con


def test_every_event_resolves_to_a_known_track(con):
    assert scalar(con, f"SELECT count(*) FROM ({RESOLVED}) WHERE got IS NULL") == 0
    assert scalar(con, f"SELECT count(*) FROM ({RESOLVED}) r ANTI JOIN dim_track d ON d.track_id = r.got") == 0


def test_track_identity(con):
    assert agreement(con, f"SELECT got = want FROM ({RESOLVED}) WHERE source <> 'lastfm'") >= 0.97
    assert agreement(con, f"SELECT got = want FROM ({RESOLVED}) WHERE source = 'lastfm'") >= 0.90
    assert agreement(con, f"SELECT got = want FROM ({RESOLVED})") >= 0.95


def test_track_attributes(con):
    common = "FROM dim_track d JOIN fx.dim_track f USING (track_id)"
    assert scalar(con, f"SELECT count(*) {common}") >= 480
    assert agreement(con, f"SELECT d.recording_year = f.recording_year {common}") >= 0.99
    assert agreement(con, f"SELECT d.work_year = f.work_year {common}") >= 0.98
    assert agreement(con, f"SELECT d.base_norm = f.base_norm AND d.mix_desc IS NOT DISTINCT FROM f.mix_desc {common}") >= 0.99
    assert agreement(con, f"SELECT d.is_remix = f.is_remix AND d.is_longform_mix = f.is_longform_mix {common}") >= 0.99
    assert agreement(con, f"SELECT abs(d.duration_ms - f.duration_ms) <= 2000 {common}") >= 0.99
    assert agreement(con, f"SELECT d.artist_norm = f.artist_norm {common}") >= 0.99
    assert agreement(con, f"SELECT d.title = f.title {common}") >= 0.98
    assert agreement(con, f"SELECT d.lastfm_listeners IS NOT DISTINCT FROM f.lastfm_listeners {common}") >= 0.95


def test_track_invariants(con):
    assert scalar(con, "SELECT count(*) FROM dim_track WHERE work_id <> artist_norm || '::' || base_norm") == 0
    assert scalar(con, "SELECT count(*) FROM dim_track d ANTI JOIN dim_artist a ON a.artist_id = d.primary_artist_id") == 0
    assert scalar(con, "SELECT count(*) FROM dim_track WHERE duration_ms IS NOT NULL AND duration_source IS NULL") == 0
    assert scalar(con, "SELECT count(*) FROM dim_track WHERE work_year > recording_year") == 0


def test_scenario_multi_uri_remaster_longform(con):
    multi = scenario(con, "multi_uri", "track_id")
    assert scalar(con, "SELECT count(*) FROM track_uri_map WHERE track_id = ?", [multi]) == 3
    assert scalar(con, "SELECT recording_year FROM dim_track WHERE track_id = ?", [multi]) == 2008
    orig, rem = scenario(con, "remaster", "track_id_original"), scenario(con, "remaster", "track_id_remaster")
    rows = con.execute("SELECT track_id, work_id, recording_year, work_year FROM dim_track WHERE track_id IN (?, ?) "
                       "ORDER BY recording_year", [orig, rem]).fetchall()
    assert [r[0] for r in rows] == [orig, rem] and rows[0][1] == rows[1][1]
    assert (rows[0][2], rows[0][3], rows[1][2], rows[1][3]) == (2008, 2008, 2021, 2008)
    assert scalar(con, "SELECT is_longform_mix FROM dim_track WHERE track_id = ?", [scenario(con, "longform", "track_id")])
    assert not scalar(con, "SELECT is_longform_mix FROM dim_track WHERE track_id = ?",
                      [scenario(con, "long_track", "track_id")])


def test_artists(con):
    on = "FROM dim_artist d JOIN fx.dim_artist f USING (artist_norm)"
    fx_n = scalar(con, "SELECT count(*) FROM fx.dim_artist")
    assert scalar(con, f"SELECT count(*) {on}") >= 0.97 * fx_n
    assert scalar(con, "SELECT count(*) FROM dim_artist") <= 1.1 * fx_n
    assert agreement(con, f"SELECT d.name = f.name {on}") >= 0.95
    assert agreement(con, f"SELECT d.spotify_artist_id IS NOT DISTINCT FROM f.spotify_artist_id {on}") >= 0.95
    assert agreement(con, f"SELECT d.artist_mbid IS NOT DISTINCT FROM f.artist_mbid {on} WHERE f.artist_mbid IS NOT NULL") >= 0.90
    assert agreement(con, f"SELECT d.lastfm_listeners IS NOT DISTINCT FROM f.lastfm_listeners {on}") >= 0.95


def test_bridge_roles(con):
    pairs = """SELECT b.track_id, a.artist_norm, b.role FROM {p}bridge_track_artist b
               JOIN {p}dim_artist a USING (artist_id)"""
    for role, min_recall in (("primary", 0.97), ("featured", 0.90), ("remixer", 1.0)):
        want = scalar(con, f"SELECT count(*) FROM ({pairs.format(p='fx.')}) WHERE role = '{role}'")
        both = f"({pairs.format(p='fx.')}) INTERSECT ({pairs.format(p='')})"
        hit = scalar(con, f"SELECT count(*) FROM ({both}) WHERE role = '{role}'")
        assert hit >= min_recall * want, f"{role}: {hit} of {want}"
    rx = scenario(con, "remixer", "artist_norm")
    assert scalar(con, """SELECT count(*) FROM bridge_track_artist b JOIN dim_artist a USING (artist_id)
                          WHERE b.role = 'remixer' AND a.artist_norm = ?""", [rx]) == 6


def test_albums(con):
    key = """SELECT al.album_norm, a.artist_norm, al.release_year, al.album_type
             FROM {p}dim_album al JOIN {p}dim_artist a ON a.artist_id = al.primary_artist_id"""
    want = scalar(con, "SELECT count(*) FROM fx.dim_album")
    hit = scalar(con, f"SELECT count(*) FROM (({key.format(p='fx.')}) INTERSECT ({key.format(p='')}))")
    assert hit >= 0.95 * want, f"{hit} of {want} albums match on name, artist, year and type"
