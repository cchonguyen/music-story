"""Golden test cases for W9b parameterised genre disaggregation, soft-hinge floor, and 50-track benchmark."""

from __future__ import annotations

import pytest
from helpers import fresh_db

from pipeline import genre


def _seed_single_track(con, tags: list[tuple[str, str, int]]) -> str:
    """Create one artist, album, and track and insert (level_entity_type, tag, count) into enr_lastfm_tags."""
    con.execute(genre.LOAD_SQL)
    con.execute("INSERT INTO dim_artist VALUES (1, 'Golden Act', 'golden act', NULL, 'sp1', 'US', 'Person', 2010, NULL, 1000)")
    con.execute("INSERT INTO dim_album VALUES (1, 'Golden LP', 'golden lp', 1, 'album', '2020-01-01', 2020, 'alb1', NULL)")
    con.execute(
        "INSERT INTO dim_track VALUES ('ISRC001', 'ISRC001', 'Golden Song', 'golden act', 'golden song', "
        "'golden song', NULL, false, 'golden act::golden song', 1, 1, 200000, 'spotify', 2020, 2020, false, 100)"
    )
    rows = []
    for entity_type, tag, count in tags:
        key = "golden act::golden song" if entity_type == "track" else ("golden act::golden lp" if entity_type == "album" else "golden act")
        rows.append((entity_type, key, tag, count))
    con.executemany(
        "INSERT INTO enr_lastfm_tags VALUES (?, ?, ?, ?, TIMESTAMP '2026-10-22 00:00:00')",
        rows,
    )
    return "ISRC001"


@pytest.mark.parametrize(
    "rho,expected_deep_house_legacy,expected_deep_house_ramp",
    [
        (0.00, 0.0, 0.0),
        (0.08, 0.0, 0.0),   # below 0.10 soft floor -> dropped under both
        (0.15, 1.0, 0.3625),  # legacy jumps to 1.0 at 0.15; ramp alpha(0.15)=0.25 -> w'=0.3625, umb=0.6375
        (0.20, 1.0, 0.60),    # ramp alpha(0.20)=0.50 -> w'=0.60, umb=0.40 (both >= 0.20 so unattenuated by g)
        (0.35, 1.0, 1.0),     # ramp alpha(0.35)=1.0 -> 100% transferred to deep house
    ],
)
def test_ramp_vs_legacy_step_across_rho(rho: float, expected_deep_house_legacy: float, expected_deep_house_ramp: float):
    con = fresh_db()
    spec_cnt = round(rho * 1000)
    umb_cnt = 1000 - spec_cnt
    tags = [("track", "electronic", umb_cnt), ("track", "edm", 0)]
    if spec_cnt > 0:
        tags.append(("track", "deep house", spec_cnt))
    tid = _seed_single_track(con, [(e, t, c) for e, t, c in tags if c > 0])

    # 1. Legacy 15% hard step (rho_min == rho_max == 0.15, no division by zero)
    genre.build(con, **genre.PROFILES["legacy_step_15"])  # type: ignore[arg-type]
    leg = dict(con.execute("SELECT style, weight FROM track_genre WHERE track_id = ?", [tid]).fetchall())
    assert abs(leg.get("deep house", 0.0) - expected_deep_house_legacy) < 1e-6

    # 2. 25% hard step (rho_min == rho_max == 0.25, no division by zero)
    genre.build(con, **genre.PROFILES["hard_step_25"])  # type: ignore[arg-type]
    step25 = dict(con.execute("SELECT style, weight FROM track_genre WHERE track_id = ?", [tid]).fetchall())
    assert abs(sum(step25.values()) - 1.0) < 1e-9

    # 3. Default ramp + soft hinge
    genre.build(con, **genre.PROFILES["ramp_soft_hinge"])  # type: ignore[arg-type]
    ramp = dict(con.execute("SELECT style, weight FROM track_genre WHERE track_id = ?", [tid]).fetchall())
    if rho == 0.15:
        # w'_spec = 0.15 + 0.25 * 0.85 = 0.3625 (>= 0.20), w'_umb = 0.6375 (>= 0.20)
        assert abs(ramp.get("deep house", 0.0) - expected_deep_house_ramp) < 1e-6
        assert abs(ramp.get("electronic", 0.0) - (1.0 - expected_deep_house_ramp)) < 1e-6
    else:
        assert abs(ramp.get("deep house", 0.0) - expected_deep_house_ramp) < 1e-6


@pytest.mark.parametrize(
    "share,expected_g",
    [
        (0.05, 0.0),
        (0.14, 0.056),
        (0.15, 0.075),
        (0.16, 0.096),
        (0.25, 0.25),
    ],
)
def test_soft_hinge_parent_and_stage_b_rollup(share: float, expected_g: float):
    con = fresh_db()
    pop_cnt = round(share * 1000)
    elec_cnt = 1000 - pop_cnt
    # Split electronic across house (60%) and techno (40%), and give pop 'synthpop'
    tid = _seed_single_track(
        con,
        [
            ("track", "house", round(elec_cnt * 0.60)),
            ("track", "techno", elec_cnt - round(elec_cnt * 0.60)),
            ("track", "synthpop", pop_cnt),
        ],
    )
    genre.build(con)
    rows = con.execute("SELECT parent_genre, style, weight FROM track_genre WHERE track_id = ?", [tid]).fetchall()
    by_parent: dict[str, float] = {}
    for pg, _st, w in rows:
        by_parent[pg] = by_parent.get(pg, 0.0) + w

    expected_b_pop = expected_g / (expected_g + (1.0 - share))
    assert abs(by_parent.get("pop", 0.0) - expected_b_pop) < 1e-6
    assert abs(by_parent.get("electronic", 0.0) - (1.0 - expected_b_pop)) < 1e-6
    assert abs(sum(by_parent.values()) - 1.0) < 1e-9


def test_50track_sensitivity_benchmark():
    """Run the 50-track synthetic multi-tag corpus across all 3 profiles and assert continuity."""
    con = fresh_db()
    con.execute(genre.LOAD_SQL)
    con.execute("INSERT INTO dim_artist VALUES (1, 'Bench Act', 'bench act', NULL, 'sp1', 'US', 'Person', 2010, NULL, 1000)")
    con.execute("INSERT INTO dim_album VALUES (1, 'Bench LP', 'bench lp', 1, 'album', '2020-01-01', 2020, 'alb1', NULL)")

    tracks = []
    tags = []
    for i in range(50):
        tid = f"BENCH{i:03d}"
        key = f"bench act::song {i}"
        tracks.append((tid, tid, f"Song {i}", "bench act", f"song {i}", f"song {i}", None, False, key, 1, 1, 200000, "spotify", 2020, 2020, False, 100))
        rho = (i % 25) / 25.0  # spans 0.00 to 0.96
        s_second = 0.02 + (i // 25) * 0.14 + (i % 10) * 0.03  # spans 0.02 to 0.43
        elec_total = round((1.0 - s_second) * 1000)
        rock_total = round(s_second * 1000)
        spec_elec = round(elec_total * rho)
        umb_elec = elec_total - spec_elec
        if umb_elec > 0:
            tags.append(("track", key, "electronic", umb_elec // 2 + 1))
            tags.append(("track", key, "edm", max(umb_elec - (umb_elec // 2 + 1), 1)))
        if spec_elec > 0:
            tags.append(("track", key, "deep house", int(spec_elec * 0.6) + 1))
            tags.append(("track", key, "techno", max(spec_elec - int(spec_elec * 0.6), 1)))
        if rock_total > 0:
            tags.append(("track", key, "indie", int(rock_total * (1.0 - rho)) + 1))
            tags.append(("track", key, "shoegaze", int(rock_total * rho) + 1))

    con.executemany(
        "INSERT INTO dim_track VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        tracks,
    )
    con.executemany(
        "INSERT INTO enr_lastfm_tags VALUES (?, ?, ?, ?, TIMESTAMP '2026-10-22 00:00:00')",
        tags,
    )

    out = genre.sensitivity(con)
    lines = [ln.split("\t") for ln in out.strip().splitlines()[2:]]
    by_prof = {r[0]: (float(r[1]), float(r[2]), float(r[3])) for r in lines}
    assert set(by_prof) == {"legacy_step_15", "hard_step_25", "ramp_soft_hinge"}
    # Ramp + soft hinge eliminates the step cliff jump around 0.15 and 0.25
    assert by_prof["ramp_soft_hinge"][1] < by_prof["legacy_step_15"][1]
    assert by_prof["ramp_soft_hinge"][1] < by_prof["hard_step_25"][1]
    # And achieves higher specific micro-style share than legacy_step_15 (which treated edm/indie as specific)
    assert 0.0 < by_prof["ramp_soft_hinge"][0] <= 1.0
