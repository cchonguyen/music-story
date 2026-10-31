# W9b: two-tier genre umbrella consolidation, continuous ramp & soft-hinge floor

Tier: Sonnet (maxTurns 30). Sequences after `specs/W9_genre.md`.
Deliverables: `sql/schema.sql` (`genre_map.is_umbrella`), `data/genre_map.csv` (5th column `is_umbrella`),
`scripts/make_fixtures.py` (`lines 936–939`), `pipeline/genre.py` (`PARENTS`, 5-column `LOAD_SQL`,
parameterised `build_sql`/`build`, `sensitivity` CLI), `tests/test_schema.py`, `tests/golden/genre_legacy_fixture.csv`,
`tests/golden/genre_cases.py`, `tests/test_genre_fixture.py`, `docs/PROJECT.md`, `STATE.md`.

## Untouched contracts
- `pipeline/artist_genre.py` (`lines 1–100`) and `tests/test_artist_genre_fixture.py` (`lines 1–62`) stay untouched to preserve the external Concert Tracker (`FORMAT = "music-story/artist-genres"`, `VERSION = 1`) export contract (`MIN_SHARE = 0.15` remains exported from `pipeline/genre.py`).

## Rules
1. `genre_map` gains `is_umbrella BOOLEAN NOT NULL` (`sql/schema.sql:405–411`). `data/genre_map.csv` header becomes `tag,style,parent_genre,is_genre,is_umbrella`.
2. Closed 13-parent list (`PARENTS` in `pipeline/genre.py`): `electronic`, `rock`, `pop`, `hip hop`, `r&b`, `jazz`, `classical`, `folk`, `metal`, `country`, `latin`, `world`, `soundtrack`.
3. Option A umbrella consolidation (`self_tag_only=False` default): all `is_umbrella = true` tags under parent $P$ (`electronic`, `edm`, `dance`, `electronica`, `electro`, `indie`, `alternative`, `rap`, and `style == P`) merge into the canonical parent-umbrella bucket `(parent_genre = P, style = P)`.
4. Continuous within-parent transfer ramp $\alpha(\rho_P)$ over $[\rho_{\min}, \rho_{\max}] = [0.10, 0.30]$ and two-stage soft-hinge floor $g(x) = x \cdot \text{clamp}((x - 0.10)/0.10, 0, 1)$ over $[0.10, 0.20]$, written with explicit `CASE` guards so `rho_min == rho_max` and `floor_min == floor_max` never divide by zero.
5. `legacy_step_15` (`rho_min=0.15, rho_max=0.15, floor_min=0.15, floor_max=0.15, self_tag_only=True, two_stage=False`) reproduces HEAD `7f935d5` `track_genre` on `dev_fixtures.duckdb` to 9 decimal places against `tests/golden/genre_legacy_fixture.csv`.
