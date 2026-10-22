"""W2 acceptance: the 60 golden match cases. Skipped until pipeline/match.py exists.

Each case is loaded into stg_spotify / stg_lastfm with raw strings only (norm
columns NULL), then pipeline.match.run(con) must fill the norm columns, write
match_links and events, and link exactly the expected pairs.
"""

from datetime import timedelta

import pytest
from helpers import fresh_db

match = pytest.importorskip("pipeline.match", reason="W2 not built yet")

from golden.match_cases import BASE_UTC, CASES


def load_case(con, case) -> None:
    for s in case.sp:
        start = BASE_UTC + timedelta(seconds=s.start)
        con.execute("""
            INSERT INTO stg_spotify (sp_id, started_at_utc, ended_at_utc, ms_played, is_full_listen, track_uri,
                                     artist_raw, track_raw, reason_end, skipped)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [s.id, start, start + timedelta(milliseconds=s.ms), s.ms, s.ms >= 30_000, f"spotify:track:case{s.id}",
             s.artist, s.track, "trackdone" if s.ms >= 30_000 else "fwdbtn", s.ms < 30_000])
    for lf in case.lfm:
        con.execute("INSERT INTO stg_lastfm (lfm_id, scrobbled_at_utc, artist_raw, track_raw) VALUES (?, ?, ?, ?)",
                    [lf.id, BASE_UTC + timedelta(seconds=lf.t), lf.artist, lf.track])


@pytest.mark.parametrize("case", CASES, ids=[f"{c.id}-{c.desc[:40]}" for c in CASES])
def test_golden_match(case):
    con = fresh_db()
    load_case(con, case)
    match.run(con)
    got = {(sp, lf): p for sp, lf, p in con.execute("SELECT sp_id, lfm_id, match_pass FROM match_links").fetchall()}
    assert got == case.expect

    dupes = {r[0] for r in con.execute("SELECT lfm_id FROM lfm_self_dupes").fetchall()}
    assert dupes == set(case.dupes)

    n_events = con.execute("SELECT count(*) FROM events").fetchone()[0]
    assert n_events == len(case.sp) + len(case.lfm) - len(case.expect) - len(case.dupes)
    both = con.execute("SELECT count(*) FROM events WHERE source = 'both'").fetchone()[0]
    assert both == len(case.expect)
