"""W0: the scenario fixture holds the facts downstream packets test against.

If one of these fails after editing make_fixtures.py, the fixture changed
meaning: fix the generator, not the test.
"""

import hashlib

from helpers import scalar, scenario

from pipeline import config


def test_fixture_is_deterministic(fixture_db_path, tmp_path):
    import subprocess
    import sys

    def digest(folder) -> str:
        h = hashlib.sha256()
        for f in sorted(folder.glob("*")):
            h.update(f.name.encode() + f.read_bytes())
        return h.hexdigest()

    subprocess.run([sys.executable, str(config.REPO_ROOT / "scripts" / "make_fixtures.py"), "--out", str(tmp_path)],
                   check=True, capture_output=True)
    assert digest(tmp_path / "raw") == digest(config.FIXTURE_RAW_DIR)


def test_every_year_is_present(fx):
    years = [r[0] for r in fx.execute("SELECT DISTINCT year(started_at_local) FROM plays ORDER BY 1").fetchall()]
    assert years == list(range(2007, 2027))


def test_source_coverage_by_era(fx):
    def share(y0: int, y1: int, src: str) -> float:
        return scalar(fx, "SELECT avg((source = ?)::INT) FROM plays WHERE year(started_at_utc) BETWEEN ? AND ?",
                      [src, y0, y1])

    assert share(2007, 2010, "lastfm") == 1.0
    assert share(2022, 2026, "both") > 0.8
    assert share(2014, 2018, "spotify") > 0.8


def test_gate1_scrobble_match_share_2023_2026(fx):
    matched = scalar(fx, """
        SELECT avg((m.lfm_id IS NOT NULL)::INT) FROM stg_lastfm l LEFT JOIN match_links m USING (lfm_id)
        WHERE year(l.scrobbled_at_utc) BETWEEN 2023 AND 2026""")
    assert matched >= 0.95


def test_planted_double_scrobbles_are_removed(fx):
    missed = scalar(fx, """
        SELECT count(*) FROM truth_lfm_dupes d
        JOIN stg_lastfm l ON l.artist_raw = d.artist AND l.track_raw = d.track
         AND epoch(l.scrobbled_at_utc)::BIGINT = d.uts""")
    assert missed == 0


def test_skip_share_is_realistic(fx):
    skips, total = fx.execute("SELECT count(*) FILTER (ms_played < 30000), count(*) FROM stg_spotify").fetchone()
    assert 0.18 < skips / total < 0.32


def test_staple_artist_every_year(fx):
    n = scalar(fx, """SELECT count(DISTINCT year(p.started_at_local)) FROM plays p
                      JOIN dim_artist a USING (artist_id) WHERE a.artist_norm = ?""",
               [scenario(fx, "staple", "artist_norm")])
    assert n == 20


def test_comeback_artist_is_silent_2012_2015(fx):
    years = {r[0] for r in fx.execute("""SELECT DISTINCT year(p.started_at_local) FROM plays p
             JOIN dim_artist a USING (artist_id) WHERE a.artist_norm = ?""",
             [scenario(fx, "comeback", "artist_norm")]).fetchall()}
    assert years.isdisjoint({2012, 2013, 2014, 2015})
    assert {2008, 2011, 2016, 2026} <= years


def test_flash_artist_only_2013(fx):
    years = {r[0] for r in fx.execute("""SELECT DISTINCT year(p.started_at_local) FROM plays p
             JOIN dim_artist a USING (artist_id) WHERE a.artist_norm = ?""",
             [scenario(fx, "flash", "artist_norm")]).fetchall()}
    assert years == {2013}


def test_binge_track(fx):
    n = scalar(fx, """SELECT count(*) FROM plays WHERE track_id = ?
                      AND started_at_local::DATE BETWEEN '2019-05-01' AND '2019-05-14'""",
               [scenario(fx, "binge", "track_id")])
    assert n >= 24


def test_remixer_outplays_the_originals(fx):
    remixer = scenario(fx, "remixer", "artist_norm")
    remixes, originals = fx.execute("""
        WITH rx AS (SELECT DISTINCT b.track_id, t.work_id FROM bridge_track_artist b
                    JOIN dim_artist a USING (artist_id) JOIN dim_track t USING (track_id)
                    WHERE b.role = 'remixer' AND a.artist_norm = ?)
        SELECT count(*) FILTER (p.track_id IN (SELECT track_id FROM rx)),
               count(*) FILTER (p.track_id NOT IN (SELECT track_id FROM rx))
        FROM plays p JOIN dim_track t USING (track_id)
        WHERE t.work_id IN (SELECT work_id FROM rx) AND year(p.started_at_local) >= 2018""",
        [remixer]).fetchone()
    assert remixes > originals


def test_multi_uri_recording_keeps_original_year(fx):
    tid = scenario(fx, "multi_uri", "track_id")
    assert scalar(fx, "SELECT count(*) FROM track_uri_map WHERE track_id = ?", [tid]) == 3
    assert scalar(fx, "SELECT recording_year FROM dim_track WHERE track_id = ?", [tid]) == 2008


def test_remaster_shares_work(fx):
    o, m = scenario(fx, "remaster", "track_id_original"), scenario(fx, "remaster", "track_id_remaster")
    rows = dict(fx.execute("SELECT track_id, (work_id, recording_year, work_year) FROM dim_track "
                           "WHERE track_id IN (?, ?)", [o, m]).fetchall())
    assert rows[o][0] == rows[m][0]
    assert rows[m][1] == 2021 and rows[m][2] == 2008


def test_longform_flags(fx):
    flag = lambda k: scalar(fx, "SELECT is_longform_mix FROM dim_track WHERE track_id = ?",
                            [scenario(fx, k, "track_id")])
    assert flag("longform") is True
    assert flag("long_track") is False
    assert scalar(fx, """SELECT count(*) FROM plays p JOIN dim_track t USING (track_id)
                         WHERE t.is_longform_mix AND p.completion_ratio IS NOT NULL""") == 0


def test_zz_block_stays_unknown(fx):
    n_known = scalar(fx, """SELECT count(*) FROM plays WHERE source <> 'lastfm' AND country IS NOT NULL
                            AND started_at_utc::DATE BETWEEN '2016-03-03' AND '2020-08-29'""")
    assert n_known == 0
    assert scalar(fx, "SELECT count(DISTINCT tz) FROM plays WHERE country IS NULL") == 1


def test_travel_uses_local_zones(fx):
    zones = dict(fx.execute("SELECT country, any_value(tz) FROM plays WHERE country IS NOT NULL GROUP BY 1").fetchall())
    assert zones["JP"] == "Asia/Tokyo" and zones["FR"] == "Europe/Paris" and zones["US"] == "America/Los_Angeles"


def test_sessions_cover_every_play_and_skip(fx):
    n_events = scalar(fx, "SELECT (SELECT count(*) FROM plays) + (SELECT count(*) FROM skips)")
    assert scalar(fx, "SELECT sum(n_plays + n_skips) FROM sessions") == n_events
    assert scalar(fx, "SELECT count(*) FROM plays WHERE session_index = 1") + \
        scalar(fx, "SELECT count(*) FROM skips WHERE session_index = 1") == scalar(fx, "SELECT count(*) FROM sessions")


def test_podcasts_and_video_never_reach_staging(fx):
    assert scalar(fx, "SELECT count(*) FROM raw_spotify WHERE spotify_track_uri IS NULL") > 0
    assert scalar(fx, "SELECT count(*) FROM raw_spotify WHERE is_video") > 0
    assert scalar(fx, "SELECT count(*) FROM stg_spotify") == scalar(
        fx, "SELECT count(*) FROM raw_spotify WHERE spotify_track_uri IS NOT NULL AND NOT is_video")
