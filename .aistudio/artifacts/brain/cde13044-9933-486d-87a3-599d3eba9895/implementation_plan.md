# Revised Implementation Plan (v5): Two-Tier Genre Taxonomy, Track Lineage X-Ray & Synchronized Views

This v5 plan resolves items A–E from the review request and aligns strictly with `CLAUDE.md`, `sql/schema.sql`, `specs/W9_genre.md`, `specs/W10_charts.md`, and `specs/W10b_explorer.md`.

---

## 1. Resolution of Review Concerns

### 1. Explorer Payload Budget, 4-Tuple Key & Play-Weighted `mart_genre_xray` Aggregation
- **No lineage strings on `explorer_plays`:** `sql/marts/40_explorer.sql` will **not** add `secondary_styles` or `tag_source` to `explorer_plays`. Every play row stays on the compact schema (`day`, `hour`, `weekday` on `sql/marts/40_explorer.sql:22–24`; `artist_norm`, `title_norm`, `parent_genre`, `style` on `sql/marts/40_explorer.sql:28–31`) to protect Zstd dictionary compression and the 20 MiB budget (`.spec/SYSTEM_SPEC.md` §1).
- **Zero Genre Disagreement via Unique 4-Tuple Key `(artist_norm, title_norm, parent_genre, style)`:**
  - Two different `track_id`s (e.g., an album cut and a compilation remaster with different ISRCs) can share `(artist_norm, title_norm)` while carrying different top `(parent_genre, style)` assignments in `explorer_plays`.
  - `mart_genre_xray` is keyed uniquely on the 4-tuple **`(artist_norm, title_norm, parent_genre, style)`** (`sql/marts/40_explorer.sql:28–31`) and exports **all** genre-classified 4-tuples present in `plays`/`skips`.
  - **Play-Weighted Aggregation Rule Across Member `track_id`s Sharing a 4-Tuple:** When multiple `track_id`s map to the same `(artist_norm, title_norm, parent_genre, style)`, let $n_t$ be the non-incognito play count of `track_id` $t$ and $w_t = \max(n_t, 1)$:
    - `track_id`, `title`, `artist`: chosen from the dominant recording via `arg_max(col, (n_t, track_id))`.
    - `primary_weight`: play-weighted mean $\sum_t (w_t \cdot \text{weight}_t) / \sum_t w_t$.
    - `level`: highest-precedence contributing level across member `track_id`s (`'track'` > `'album'` > `'artist'`).
    - `secondary_styles`: union of non-primary kept styles on member `track_id`s, play-weighted by $\sum_t (w_t \cdot \text{weight}_{t,s}) / \sum_t w_t$ and formatted in descending weight order (`"style_b (32%) · style_c (18%)"`).
    - `suppressed_umbrellas`: sorted distinct union `string_agg(DISTINCT u_tag, ', ' ORDER BY u_tag)` of raw `is_umbrella = true` tags present on the member `track_id`s / primary artist.
    - `plays`, `listen_hours`, `skip_rate`, `peak_local_hour`, `top_country`, `first_year`, `last_year`: aggregated directly over the pooled plays/skips of all member `track_id`s in that 4-tuple.
  - Joining in DuckDB-Wasm via `LEFT JOIN xray USING (artist_norm, title_norm, parent_genre, style)` guarantees by construction that every matched row agrees with `explorer_plays.parent_genre` and `explorer_plays.style`, never duplicates play rows (`postJoinPlays === preJoinPlays`), and leaves zero unmatched classified plays. Plays with `parent_genre IS NULL` are reported as `Unclassified Plays (no genre tags)`.
- **20 MiB Size Guard (`.spec/PROGRESS.md` Slice 4):** `pipeline/site_data.py:parquet_bytes()` enforces `MAX_PARQUET_BYTES = 20 * 1024 * 1024` (raising `ValueError` if exceeded), covered by `test_parquet_bytes_size_guard` in `tests/test_site_data.py`.

### 2. Single Umbrella Representation, Closed 13-Parent List & Only Schema Change (`genre_map.is_umbrella`)
- **The ONLY change to `sql/schema.sql` across all four packets** is adding `is_umbrella BOOLEAN NOT NULL` on `genre_map` (Layer 7, lines 405–410 of `sql/schema.sql`), matched by a 5th column `is_umbrella` in `data/genre_map.csv` (`tag,style,parent_genre,is_genre,is_umbrella`).
  - **Closed 13-Parent Genre List (`specs/W9_genre.md:17` `[VERIFIED at HEAD]`):** `electronic`, `rock`, `pop`, `hip hop`, `r&b`, `jazz`, `classical`, `folk`, `metal`, `country`, `latin`, `world`, `soundtrack`. (`pipeline/genre.py` at HEAD only defines `GENRE_MAP_CSV` and `MIN_SHARE = 0.15` at `lines 16–17`; Packet 1 adds `PARENTS: tuple[str, ...]` to `pipeline/genre.py`.)
  - `is_umbrella = true` marks broad scene/parent catch-alls:
    - `electronic`: `electronic`, `edm`, `dance`, `electronica`, `electro`, `club`, `rave`
    - `rock`: `rock`, `indie`, `alternative`, `alt rock`
    - `pop`: `pop`
    - `hip hop`: `hip hop`, `rap`
    - All other `style == parent_genre` self-tags (`r&b`, `jazz`, `classical`, `folk`, `metal`, `country`, `latin`, `world`, `soundtrack`).
  - `track_genre` in `sql/schema.sql` remains **unchanged** (`track_id, parent_genre, style, weight, level`).
  - **Fixture & `LOAD_SQL` 5-Column `is_umbrella` Rule (`scripts/make_fixtures.py:936–939` & `pipeline/genre.py:19–30` `[VERIFIED at HEAD 7f935d5]`):**
    - `scripts/make_fixtures.py:936`: `gm = [(t, t, pg, True, t == pg) for t, pg in parent.items()]` — parent self-tags (`t == pg`, i.e., `"hip hop"`) get `is_umbrella = True` under the §1.2 rule, and specific fixture styles (`t != pg`: `"indie rock"`, `"electro house"`, `"dubstep"`, `"house"`, `"techno"`, `"ambient"`, `"k-pop"`, `"v-pop"`, `"j-pop"`) get `is_umbrella = False`.
    - `scripts/make_fixtures.py:937–939`: non-genre fixture rows (`is_genre = False`) get `is_umbrella = False` (`[("seen live", None, None, False, False), ("favorites", None, None, False, False)]` and `[(str(y), None, None, False, False) for y in range(1995, 2019)]`) before `insert(con, "genre_map", gm)` at line 939.
    - `pipeline/genre.py:19–30` (`LOAD_SQL` block): both `INSERT INTO genre_map` statements are updated to 5 columns:
      1. CSV `INSERT` (`lines 21–23`): `SELECT lower(trim(tag)), nullif(trim(style), ''), nullif(trim(parent_genre), ''), lower(trim(is_genre)) = 'true', lower(trim(is_umbrella)) = 'true' FROM read_csv(...)`
      2. Year/decade `INSERT` (`lines 24–29`): `INSERT INTO genre_map SELECT DISTINCT t, NULL, NULL, false, false FROM (...) WHERE t NOT IN (SELECT tag FROM genre_map);` (taking `false` as the 5th value since generated year/decade strings are not umbrellas).
- **Contract Synchronisation (`CLAUDE.md` Rule 2):** In the same commit as the `sql/schema.sql` update to `genre_map`, Packet 1 (`W9b`) updates `sql/schema.sql`, `tests/test_schema.py` (`test_genre_map_columns`), `STATE.md`, and `docs/PROJECT.md`.

### 3. Ambiguity-Free Mathematical Rule, Cliff Elimination & Parent Genre Conservation
- **Definitions within each `(track_id, parent_genre)` partition:**
  After per-level normalization (`track` $\times 1.0$, `album` $\times 0.7$, `artist` $\times 0.5$), let a track's raw weight for style $s$ under parent genre $P$ be $w_{P,s}$. Partition the styles under $P$ into:
  - **Specific micro-styles** $S_P = \{s \in P \mid \text{is\_umbrella}(s) = \text{false}\}$ with sum:
    $$W_{\text{spec}}(P) = \sum_{s \in S_P} w_{P,s}$$
  - **Umbrella styles** $U_P = \{u \in P \mid \text{is\_umbrella}(u) = \text{true}\}$ with sum:
    $$W_{\text{umb}}(P) = \sum_{u \in U_P} w_{P,u}$$
  - **Total parent weight** on the track:
    $$W_{\text{parent}}(P) = W_{\text{spec}}(P) + W_{\text{umb}}(P)$$
  - **Specificity share within the parent genre**:
    $$\rho_P = \frac{W_{\text{spec}}(P)}{W_{\text{parent}}(P)} \in [0, 1] \quad (\text{when } W_{\text{parent}}(P) > 0)$$
- **Replacing `pipeline/genre.py:86–109` with a Single Parameterised Rule (Option 2 Selected — `[VERIFIED at HEAD 7f935d5]`):**
  - At HEAD, `pipeline/genre.py:86–105` (`parent_stats` and `disagg` CTEs) implements a hardcoded `MIN_SHARE = 0.15` step reallocation of bare self-tags (`style = parent_genre` $\to$ `style <> parent_genre` when `coalesce(sub_w, 0) >= 0.15 * parent_w`), followed by single-stage hard pruning in `kept` (`lines 106–109`). That existing rule has two flaws: (i) it creates a hard cliff between $\rho_P = 0.14$ ($0\%$ transfer) and $\rho_P = 0.16$ ($100\%$ transfer), and (ii) it treats scene-wide umbrellas with `style <> parent_genre` (`edm`, `dance`, `electronica`, `indie`, `alternative`, `rap`) as specific sub-styles.
  - **Option 2 (Single Parameterised Builder in `pipeline/genre.py`, No Separate Copy):** Packet 1 **replaces** `pipeline/genre.py:86–109` with a single parameterised SQL builder `build(con, *, rho_min=0.10, rho_max=0.30, floor_min=0.10, floor_max=0.20, self_tag_only=False, two_stage=True)`. Both $\alpha(\rho_P)$ and $g(x)$ are written as explicit SQL `CASE` expressions whose `>= max` and `< min` branches execute **before** the linear interpolation branch, so `rho_min == rho_max` and `floor_min == floor_max` never divide by zero:
    $$\alpha(\rho_P;\, \rho_{\min}, \rho_{\max}) = \begin{cases} 1.0 & \text{if } \rho_P \ge \rho_{\max} \\ 0.0 & \text{if } \rho_P < \rho_{\min} \\ \dfrac{\rho_P - \rho_{\min}}{\rho_{\max} - \rho_{\min}} & \text{otherwise } (\rho_{\min} \le \rho_P < \rho_{\max} \text{ and } \rho_{\min} < \rho_{\max}) \end{cases}$$
    ```sql
    -- SQL expression in pipeline/genre.py (zero division-by-zero when rho_min == rho_max):
    CASE
        WHEN rho_p >= :rho_max THEN 1.0
        WHEN rho_p <  :rho_min THEN 0.0
        ELSE (rho_p - :rho_min) / nullif(:rho_max - :rho_min, 0.0)
    END
    ```
    - When `self_tag_only=True`, the umbrella predicate in SQL is `style = parent_genre` (instead of `is_umbrella = true`), and when `two_stage=False`, pruning runs in a single track-level stage (`g(w / track_w) > 0` followed by `w / sum(w) OVER (PARTITION BY track_id)`), matching HEAD `lines 106–116` identically.
    - This allows `pipeline.genre sensitivity` and `tests/golden/genre_cases.py` to evaluate all three regimes side by side through the same function:
      1. **15% Hard Step (`legacy_step_15`):** `rho_min=0.15, rho_max=0.15, floor_min=0.15, floor_max=0.15, self_tag_only=True, two_stage=False` — reproduces HEAD `7f935d5` `pipeline/genre.py:86–116` on `(track_id, parent_genre, style, round(weight, 9), level)` against the committed snapshot `tests/golden/genre_legacy_fixture.csv` (verified by `test_legacy_step_15_matches_head_fixture_rounded_9dp`).
      2. **25% Hard Step (`hard_step_25`):** `rho_min=0.25, rho_max=0.25, floor_min=0.25, floor_max=0.25, self_tag_only=False, two_stage=True`.
      3. **Default Production Ramp + Soft Hinge (`ramp_soft_hinge`):** `rho_min=0.10, rho_max=0.30, floor_min=0.10, floor_max=0.20, self_tag_only=False, two_stage=True`:
         - When $\rho_P < 0.10$ (specific tags are negligible noise $< 10\%$ of the parent's weight), $\alpha = 0$: umbrella weights are untouched.
         - When $0.10 \le \rho_P < 0.30$, $\alpha$ ramps linearly from $0$ to $1$: a fraction $\alpha$ of $W_{\text{umb}}(P)$ transfers proportionally to the specific styles $s \in S_P$, and $(1 - \alpha)$ stays on the umbrella styles.
         - When $\rho_P \ge 0.30$ (specific micro-styles form at least $30\%$ of the parent's weight), $\alpha = 1$: $100\%$ of $W_{\text{umb}}(P)$ is redistributed across $s \in S_P$ in proportion to $\frac{w_{P,s}}{W_{\text{spec}}(P)}$:
           $$w'_{P,s} = w_{P,s} + \alpha(\rho_P) \cdot W_{\text{umb}}(P) \cdot \frac{w_{P,s}}{W_{\text{spec}}(P)} \quad (\forall s \in S_P)$$
           $$w'_{P,u} = (1 - \alpha(\rho_P)) \cdot w_{P,u} \quad (\forall u \in U_P)$$
- **`pipeline/artist_genre.py` & External Concert Tracker Contract (`FORMAT = "music-story/artist-genres"`, `VERSION = 1` at `lines 1–14, 26–56` — `[VERIFIED at HEAD 7f935d5]`):**
  - `pipeline/artist_genre.py` (`lines 1–100`) is a standalone CLI export (`build/artist_genres.json`) that feeds the external **Concert Tracker** application (`concert.charliechonguyen.com`) under `FORMAT = "music-story/artist-genres"`, `VERSION = 1`; it is not read by `track_genre` or any `music-story` mart.
  - **Decision:** Explicitly preserve the legacy `MIN_SHARE = 0.15` hard floor (`QUALIFY cnt >= 0.15 * sum(cnt) OVER (PARTITION BY artist_id)` at `pipeline/artist_genre.py:50`) and `VERSION = 1` contract for `pipeline/artist_genre.py`. `pipeline/genre.py:17` keeps `MIN_SHARE = 0.15` exported for `pipeline/artist_genre.py:26`, and `pipeline/artist_genre.py` (`lines 1–100`) and `tests/test_artist_genre_fixture.py` (`lines 1–62`) remain **untouched** so Concert Tracker's expected output does not change.
- **Umbrella Consolidation (Option A Confirmed by Owner on 2026-10-31; Option B Dropped):**
  - All `is_umbrella = true` tags $u \in U_P$ under parent $P$ (`electronic`, `edm`, `dance`, `electronica`, `indie`, `alternative`, `rap`, and `style == P`) merge into a single canonical parent-umbrella bucket `(parent_genre = P, style = P)` with raw weight $W_{\text{umb}}(P)$ on the charts.
  - Raw umbrella tag names (`edm`, `dance`, `indie`, `alternative`, `rap`) remain in `mart_genre_xray.suppressed_umbrellas` for inspection in the Song Genre X-Ray table.
  - When a track has *only* umbrella tags under $P$ ($W_{\text{spec}}(P) = 0 \implies \rho_P = 0 \implies \alpha(0) = 0$), $100\%$ of $W_{\text{umb}}(P)$ stays on `style = P` (`electronic`, `rock`, `hip hop`, etc.).
- **Cliff-Free Soft-Hinge Floor $g(x)$ at Both Parent and Style Levels & Exact Conservation Statement:**
  - **Eliminating the Parent-Level and Style-Level Cliffs (`CASE`-guarded against `floor_min == floor_max`):** Replace the hard step cutoff in `track_genre` with a piecewise $C^0$-continuous soft-hinge attenuation function parameterized by $(x_{\min}, x_{\max})$ with default $(0.10, 0.20)$ centered on $0.15$:
    $$g(x;\, x_{\min}, x_{\max}) = \begin{cases} x & \text{if } x \ge x_{\max} \\ 0.0 & \text{if } x < x_{\min} \\ x \cdot \dfrac{x - x_{\min}}{x_{\max} - x_{\min}} & \text{otherwise } (x_{\min} \le x < x_{\max} \text{ and } x_{\min} < x_{\max}) \end{cases}$$
    ```sql
    -- SQL expression in pipeline/genre.py (zero division-by-zero when floor_min == floor_max):
    CASE
        WHEN x >= :floor_max THEN x
        WHEN x <  :floor_min THEN 0.0
        ELSE x * (x - :floor_min) / nullif(:floor_max - :floor_min, 0.0)
    END
    ```
    - Under the default $(x_{\min}, x_{\max}) = (0.10, 0.20)$: for noise shares $x \le 0.10$, $g(x) = 0$ (dropped completely); as $x$ rises from $0.10$ to $0.20$, $g(x)$ increases continuously from $0.0$ ($g(0.10)=0$) through $g(0.14)=0.056$, $g(0.15)=0.075$, $g(0.16)=0.096$ up to $g(0.20)=0.20$ with **zero cliff jump**; and for $x \ge 0.20$, $g(x) = x$.
    - When $x_{\min} = x_{\max} = \theta$ (`legacy_step_15` with $\theta = 0.15$, or `hard_step_25` with $\theta = 0.25$), the first two `WHEN` branches (`x >= :floor_max THEN x` and `x < :floor_min THEN 0.0`) are exhaustive and evaluate the exact hard step filter $x \ge \theta$ without ever dividing by zero.
  - **Two-Stage (`two_stage=True`, default) vs. Single-Stage (`two_stage=False`, `legacy_step_15`) Application:**
    - When `two_stage=True` (default `ramp_soft_hinge` and `hard_step_25`):
      - *Stage A (Parent Soft Floor):* Let $W_{\text{track}} = \sum_Q W_{\text{parent}}(Q)$ and $s_P = W_{\text{parent}}(P) / W_{\text{track}}$. Each parent's attenuated weight is $\tilde{W}_P = g(s_P; x_{\min}, x_{\max})$ (or if all parents have $\tilde{W}_P = 0$, keep the single largest parent so a tagged track never becomes unclassified), and renormalise surviving parents to sum to $1.0$:
        $$B_P = \frac{\tilde{W}_P}{\sum_Q \tilde{W}_Q}, \quad \sum_P B_P = 1.0$$
      - *Stage B (Within-Parent Style Soft Floor):* Within each surviving parent $P$ ($B_P > 0$), apply $g(w'_{P,s} / W_{\text{track}}; x_{\min}, x_{\max})$ to each style $s$ (or keep the single heaviest style in $P$ if all styles in $P$ evaluate to $0$), and scale the surviving styles of $P$ so their weights sum to $B_P$.
    - When `two_stage=False` (`legacy_step_15`): skips Stage A parent-budget locking and applies $g(w'_{P,s} / W_{\text{track}}; 0.15, 0.15) > 0$ directly across the track's styles in `disagg`, then renormalises kept styles by `w / sum(w) OVER (PARTITION BY track_id)`—matching HEAD `pipeline/genre.py:106–116` identically.
  - **Precise Conservation Invariants:**
    1. **Pre-Prune Conservation (`test_pre_prune_parent_totals_conserved`):** Before Stage A attenuation/renormalisation, within-parent redistribution conserves every parent's raw weight identically ($\sum_{s} w'_{P,s} = W_{\text{parent}}(P)$ for all parents).
    2. **Post-Prune Disaggregation Invariance (`test_post_prune_parent_totals_invariant_to_alpha`):** Zeroing noise parents ($s_P \le 0.10$) and attenuating $0.10 < s_P < 0.20$ before renormalising to $\sum_P B_P = 1.0$ intentionally transfers pruned/attenuated noise weight onto surviving parents compared to raw unpruned tags. However, because $B_P$ depends **only** on $W_{\text{parent}}(P)$ and is independent of $\alpha(\rho_P)$ and how $P$ splits into sub-styles, post-prune parent budgets $B_P$ (and `mart_genre_year` totals per parent) are **100% invariant to sub-style disaggregation** ($\alpha(\rho_P)$ vs. $\alpha \equiv 0$).
- **Sensitivity Check Specification (Item E — Metric, Dataset, and Recording Location):**
  - **Dataset:**
    1. *In-repo deterministic benchmark (`tests/golden/genre_cases.py`):* A 50-track synthetic multi-tag benchmark corpus spanning $\rho_P \in [0.0, 1.0]$ and parent share $s_P \in [0.02, 0.50]$ (required because base `dev_fixtures.duckdb` assigns a single genre per artist so $\rho_P \in \{0, 1\}$ on base fixture tracks).
    2. *Real-data CLI command (`uv run python -m pipeline.genre sensitivity`):* Runs the identical 3-rule comparison on `MUSIC_DB` (`build/music.duckdb`) on the owner's Mac.
  - **Metrics Compared Across (1) 15% Hard Step, (2) 25% Hard Step, and (3) Ramp $\alpha(\rho_P)$ on $[0.10, 0.30]$ + Soft Hinge $g(x)$ on $[0.10, 0.20]$:**
    - `specific_style_share`: Share of total `electronic` and `rock` weight assigned to specific micro-styles (`style <> parent_genre`) vs. parent umbrella (`style == parent_genre`).
    - `max_cliff_jump`: Maximum $\ell_1$ output weight jump $\max \|\mathbf{w}(\theta + 0.01) - \mathbf{w}(\theta - 0.01)\|_1$ across a $\pm 0.01$ input share perturbation around $\theta = 0.15$ and $\theta = 0.25$.
    - `mean_styles_per_track`: Mean count of kept `track_genre` rows per classified track.
  - **Where Recorded:** Recorded in a markdown table in `docs/PROJECT.md` under the Genre section and referenced in a new `docs/PROJECT.md` Decision Log row in Packet 1 (`W9b`).

### 4. Mapping Source Choice & Consequence (Item A — Option (ii) Selected)
- **Decision (Option (ii)):** Ship Packet 1 (`W9b`) with the existing 222-row `data/genre_map.csv` extended with the 5th column `is_umbrella` (which covers the synthetic `fx.genre_map` list per `test_genre_map_covers_fixture_tags`, while full coverage of all raw tags in `dev_fixtures.duckdb` is **`[UNVERIFIED]`** until `uv run python -m pipeline.genre unmapped` is run in Packet 1), and add a follow-up local curation step (`uv run python -m pipeline.genre unmapped --top 200` against `build/music.duckdb` on the owner's Mac) before running the real `build_pipeline`.
- **Consequence:** Packet 1 builds, passes all fixture/golden tests, and merges without blocking on local Mac database access or guessing unverified tag strings from memory. Until the follow-up `unmapped --top 200` pass is run on `build/music.duckdb`, any real-data micro-genre tags not yet in the 222-row map are ignored by `genre_map` and those tracks fall back to their mapped artist/album tags or parent umbrella (`style = parent_genre`).

### 5. Verified Line Citations, Untouched-File Invariants & Executable Checks (Item B)
Verified, with minor line-count corrections:
- `sql/schema.sql:186–192` (`enr_spotify_artist`), `195–209` (`enr_mb_recording`), `211–220` (`enr_mb_artist`), `226–233` (`enr_lastfm_tags`), `355–358` (`sessions.started_at_utc/local/tz`), `369–372` (`plays.started_at_utc/local/tz`), `398` (`skips`), `405–410` (`genre_map`) — **`[VERIFIED at HEAD]`**.
  - *Agent check:* `uv run pytest tests/test_schema.py -q`
- `sql/marts/10_simple.sql:61–67` (`mart_clock` uses `year(started_at_local)`, `isodow(started_at_local)`, `hour(started_at_local)`) — **`[VERIFIED at HEAD]`** *(corrected from `:44` in v4, which was `mart_artist_year`)*.
  - *Agent check:* `git diff --exit-code sql/marts/10_simple.sql`
- `sql/marts/40_explorer.sql:22–24` (`day`, `hour`, `weekday` from `e.started_at_local`) and `sql/marts/40_explorer.sql:28–31` (`artist_norm`, `title_norm`, `parent_genre`, `style`) — **`[VERIFIED at HEAD]`**.
  - *Agent check:* `git diff --exit-code sql/marts/40_explorer.sql`
- `sql/marts/50_insights.sql:127–129` (`mart_tempo_pulse` uses `hour(p.started_at_local) AS hr`, `year(p.started_at_local) AS yr`) — **`[VERIFIED at HEAD]`** *(corrected from `:153` in v4)*.
  - *Agent check:* `grep -n "started_at_local" sql/marts/50_insights.sql`
- **Untouched W5, W6, W10 marts, Concert Tracker `artist_genre` export & `tests/test_site_pages.py` (47 lines, `lines 1–47`) — `[VERIFIED at HEAD]`:**
  - `sql/marts/10_simple.sql`, `sql/marts/20_trap.sql`, `sql/marts/30_labels.sql`, `pipeline/artist_genre.py` (100 lines, `lines 1–100`), `tests/test_artist_genre_fixture.py` (62 lines, `lines 1–62`), and `tests/test_site_pages.py` are not modified in any packet.
  - Because `tests/test_site_pages.py:28–32` (`test_one_loader_per_mart`) asserts that every `mart_<name>` table in DuckDB has a matching `site/src/data/<name>.json.sh` file, Packet 2 (`W9c`) creates `site/src/data/genre_{xray,hierarchy,clock}.json.sh` in the same commit as the three new `mart_genre_*` tables.
  - *Agent check:* `git diff --exit-code sql/marts/10_simple.sql sql/marts/20_trap.sql sql/marts/30_labels.sql pipeline/artist_genre.py tests/test_artist_genre_fixture.py tests/test_site_pages.py && uv run pytest tests/test_artist_genre_fixture.py tests/test_site_pages.py -q`

### 6. Audit of Cited Test Names (Item C)
- `tests/test_genre_fixture.py` (70 lines, `lines 1–70`) — **`[VERIFIED at HEAD]`**:
  - `test_genre_map_covers_fixture_tags` (`lines 22–29`): **`[VERIFIED EXISTING]`**
  - `test_weights` (`lines 32–36`): **`[VERIFIED EXISTING]`**
  - `test_top_style_matches_fixture` (`lines 39–43`): **`[VERIFIED EXISTING]`**
  - `test_noise_tags_never_count` (`lines 46–48`): **`[VERIFIED EXISTING]`**
  - `test_umbrella_style_disaggregates_to_substyles` (`lines 51–69`): **`[VERIFIED EXISTING]`**
- `tests/test_artist_genre_fixture.py` (62 lines, `lines 1–62`) — **`[VERIFIED at HEAD, UNTOUCHED]`**:
  - Existing tests (`test_some_artists_have_genres`, `test_weights_sum_to_one_and_respect_threshold`, `test_only_mapped_genres`, `test_mbid_carried`, `test_export_file`) stay untouched to guard the `music-story/artist-genres` v1 Concert Tracker contract.

---

## 2. Work Packet Split & Sequencing Against Existing `/specs`

### Packet 1: `specs/W9b_genre_umbrella.md` (`[CORE / DATA]`, sequences after `specs/W9_genre.md`)
- **Target Files:** `sql/schema.sql`, `scripts/make_fixtures.py` (5-column `genre_map` tuples at `lines 936–939`), `data/genre_map.csv` (222 existing rows + `is_umbrella` column), `pipeline/genre.py` (keeps `MIN_SHARE = 0.15` for `artist_genre.py`, adds `PARENTS` constant, updates both `INSERT INTO genre_map` statements in `LOAD_SQL` at `lines 19–30`—adding `lower(trim(is_umbrella)) = 'true'` to the CSV `INSERT` at `lines 21–23` and `false` as the 5th column in `SELECT DISTINCT t, NULL, NULL, false, false` for the year/decade `INSERT` at `lines 24–29`—and replaces `lines 86–109` `parent_stats`/`disagg`/`kept` CTEs with the single parameterised rule supporting `legacy_step_15`, `hard_step_25`, and default `ramp_soft_hinge`), `tests/test_schema.py`, `tests/golden/genre_legacy_fixture.csv`, `tests/golden/genre_cases.py`, `tests/test_genre_fixture.py`, `docs/PROJECT.md`, `STATE.md`. *(Note: `pipeline/artist_genre.py` and `tests/test_artist_genre_fixture.py` are intentionally untouched to preserve the Concert Tracker v1 contract.)*
- **Pre-Edit Reference Snapshot Step (`tests/golden/genre_legacy_fixture.csv`):** Before modifying `sql/schema.sql`, `scripts/make_fixtures.py`, `data/genre_map.csv`, or `pipeline/genre.py`, Packet 1 first regenerates `dev_fixtures.duckdb` from unmodified HEAD `7f935d5` `scripts/make_fixtures.py` using the documented command `uv run python scripts/make_fixtures.py` (`README.md:9`, `tests/test_fixtures.py:24`), runs the unmodified HEAD `7f935d5` `pipeline.genre` builder (`SELECT track_id, parent_genre, style, printf('%.9f', round(weight, 9)) AS weight, level FROM track_genre ORDER BY track_id, parent_genre, style`), and writes the output to the committed file `tests/golden/genre_legacy_fixture.csv` with the header comment `# generated from HEAD 7f935d5 scripts/make_fixtures.py and pipeline/genre.py on dev_fixtures.duckdb (weights rounded to 9 decimal places)`. (While `scripts/make_fixtures.py:936–939` builds `gm` without calling `r`, raw-fixture determinism after editing `make_fixtures.py` is **`[UNVERIFIED until Packet 1 runs]`** and is verified by `tests/test_fixtures.py::test_fixture_is_deterministic`.)
- **CLI Commands in `pipeline/genre.py`:** Preserves `unmapped [--top N]` (`W9_genre.md` Rule 4), `summary`, `inspect`, and adds `sensitivity` (which invokes the parameterised builder in `pipeline/genre.py` across the three parameter profiles).
- **Tests (`uv run pytest -q && uv run ruff check`):**
  1. `test_schema.py::test_genre_map_columns` **`[NEW]`**: verifies `genre_map` has `(tag, style, parent_genre, is_genre, is_umbrella)`.
  2. `test_genre_fixture.py::test_genre_map_csv_hygiene` **`[NEW]`**: asserts trimmed lowercase strings, valid booleans, and `parent_genre` in `genre.PARENTS` (`specs/W9_genre.md:17`) when `is_genre = true`, and verifies `fx.genre_map` has `is_umbrella = (style == parent_genre)` when `is_genre = true` and `is_umbrella = false` when `is_genre = false`.
  3. `test_genre_fixture.py::test_legacy_step_15_matches_head_fixture_rounded_9dp` **`[NEW]`**: runs `genre.build(con, rho_min=0.15, rho_max=0.15, floor_min=0.15, floor_max=0.15, self_tag_only=True, two_stage=False)` on the fixture DB, rounds `weight` to 9 decimal places (`round(weight, 9)`), and asserts exact row equality (`ORDER BY track_id, parent_genre, style`) against `tests/golden/genre_legacy_fixture.csv` (including verifying the `# generated from HEAD 7f935d5` header comment), plus verifies on a multi-style parent track that `two_stage=False` matches HEAD single-stage pruning.
  4. `test_fixtures.py::test_fixture_is_deterministic` **`[EXISTING]`**: after editing `scripts/make_fixtures.py:936–939` and regenerating `dev_fixtures.duckdb` via `uv run python scripts/make_fixtures.py`, runs `uv run pytest tests/test_fixtures.py -q` to verify `FIXTURE_RAW_DIR` SHA-256 determinism.
  5. `test_genre_fixture.py::test_noise_share_under_soft_floor_is_dropped` **`[NEW]`**: verifies shares $\le 0.10$ are zeroed by $g(x)$.
  6. `test_genre_fixture.py::test_pre_prune_conservation_and_post_prune_disaggregation_invariance` **`[NEW]`**: verifies pre-prune parent weight conservation and post-prune invariance of $B_P$ and `mart_genre_year` to $\alpha(\rho_P)$.
  7. `tests/golden/genre_cases.py` **`[NEW]`**: calls the parameterised `pipeline/genre.py` builder across `legacy_step_15` (`rho_min == rho_max == 0.15`, verifying no division by zero), `hard_step_25` (`rho_min == rho_max == 0.25`), and default `ramp_soft_hinge` at $\rho \in \{0.0, 0.08, 0.15, 0.20, 0.35\}$, soft-hinge $g(x)$ at $x \in \{0.05, 0.14, 0.15, 0.16, 0.25\}$, Stage B roll-up to $B_P$, and the 50-track sensitivity benchmark.

---

### Packet 2: `specs/W9c_genre_xray_marts.md` (`[CORE / DATA]`, sequences after `W5`, `W6`, `W10`)
- **Target Files:** `sql/marts/50_insights.sql` (`mart_genre_xray`, `mart_genre_hierarchy`, `mart_genre_clock`), `pipeline/site_data.py` (loaders + 20 MiB `parquet_bytes` guard), `scripts/generate_fixture_marts.py` (appends `genre_xray.json`, `genre_hierarchy.json`, `genre_clock.json` after existing RNG-consuming loops without altering any `r.*` call order), `site/src/data/genre_{xray,hierarchy,clock}.json.sh` (required so `tests/test_site_pages.py::test_one_loader_per_mart` stays green), `tests/test_marts_fixture.py`, `tests/test_site_data.py`.
- **Tests (`uv run pytest -q && uv run ruff check`):**
  1. `test_genre_xray_unique_on_4tuple_key` **`[NEW]`**: asserts `COUNT(*) == COUNT(DISTINCT (artist_norm, title_norm, parent_genre, style))` in `mart_genre_xray`.
  2. `test_explorer_left_join_xray_conserves_rows_and_matches_genre` **`[NEW]`**: runs `explorer_plays LEFT JOIN mart_genre_xray USING (artist_norm, title_norm, parent_genre, style)` in DuckDB, asserting row-count equality with `explorer_plays` and `0` unmatched classified plays.
  3. `test_genre_clock_uses_started_at_local` **`[NEW]`**, `test_parquet_bytes_size_guard` **`[NEW]`** (20 MiB limit), and `test_generate_fixture_marts_rng_parity` **`[NEW]`** (single RNG parity check across the plan: verifies `scripts/generate_fixture_marts.py` `year.json` and `explorer_plays.json` row/play counts match `dev_fixtures.duckdb` `mart_year` and `explorer_plays`).

---

### Packet 3: `specs/W10c_genres_page.md` (`[UI / VISUAL]`, sequences after `specs/W10_charts.md`)
- **Target Files:** `site/src/genres.md`.
- **Features & Verification (`uv run pytest tests/test_site_pages.py -q && cd site && npm run build`):** Preserves existing W10 charts and `<!-- story: ... -->` comments; adds Parent Genre summary table, Genre $\to$ Sub-Style $\to$ Artist hierarchy chart + table, Local-Time Circadian Genre heatmap + daypart filter, and Song Genre X-Ray table.

---

### Packet 4: `specs/W10d_explorer_and_tables.md` (`[UI / VISUAL]`, sequences after `W10b_explorer.md` and `W10_charts.md`)
- **Target Files:** `site/src/explorer.md`, `site/src/index.md`, `site/src/artists.md`, `site/src/songs.md`, `site/src/habits.md`, `site/src/places.md`.
- **Features & Verification (`uv run pytest tests/test_site_data.py tests/test_site_pages.py -q && cd site && npm run build`):**
  1. `site/src/explorer.md`: Registers `genre_xray.json` as table `xray` in DuckDB-Wasm, joins via `LEFT JOIN xray USING (artist_norm, title_norm, parent_genre, style)`, asserts in-browser that `postJoinPlays === preJoinPlays` and `unmatchedClassifiedPlays === 0`, reports `Classified Plays` and `Unclassified Plays (no genre tags)`, and adds multi-facet subfilters (Date/Year range, Parent Genre, Sub-Style, Local Hour/Daypart, Weekday/Weekend, Country, Platform, Skip Mode).
  2. Synchronized `Inputs.table` views paired with the existing W10 charts on `index.md`, `artists.md`, `songs.md`, `habits.md`, and `places.md`.

---

## 3. One-Line Change Log (v4 $\to$ v5)

- **Item A (Mapping Source):** Picked option (ii)—shipping Packet 1 with the existing 222-row map + `is_umbrella` (with full `dev_fixtures.duckdb` raw-tag coverage marked **`[UNVERIFIED]`** pending `pipeline.genre unmapped`) and running `unmapped --top 200` on the owner's Mac as a follow-up before real `build_pipeline`—because the cloud environment has no access to the real SQLite HTTP cache.
- **Item B (Line Citations & Untouched Files):** Verified cited files and lines at HEAD (with off-by-one line-count corrections for `test_site_pages.py` at 47 lines, `test_genre_fixture.py` at 70 lines, and `test_artist_genre_fixture.py` at 62 lines), corrected `mart_clock` (`10_simple.sql:61–67`) and `mart_tempo_pulse` (`50_insights.sql:127–129`), added executable `git diff`/`pytest` checks, and moved `site/src/data/genre_*.json.sh` creation into Packet 2 so `test_site_pages.py::test_one_loader_per_mart` passes.
- **Item C (Existing Test Audit & Concert Tracker Contract):** Audited `tests/test_genre_fixture.py` and `tests/test_artist_genre_fixture.py` at HEAD `7f935d5`, and explicitly kept `pipeline/artist_genre.py` (`MIN_SHARE = 0.15`, `VERSION = 1`) and `tests/test_artist_genre_fixture.py` untouched so the external Concert Tracker (`music-story/artist-genres` v1) contract is preserved.
- **Item D (Option A Confirmed):** Removed all conditional "Proceed approves Option A unless Option B" phrasing and recorded Option A as confirmed by the owner on 2026-10-31.
- **Item E (Sensitivity Table Spec):** Defined the exact three metrics (`specific_style_share`, `max_cliff_jump`, `mean_styles_per_track`), the 50-track synthetic benchmark + `pipeline.genre sensitivity` real-DB CLI, and the target section in `docs/PROJECT.md`.
- **Closed 13-Parent Constant (`PARENTS`):** Cited `specs/W9_genre.md:17` as the sole existing source at HEAD and specified that Packet 1 adds `PARENTS` to `pipeline/genre.py`.
- **Parameterised Rule in `pipeline/genre.py` (Option 2 + Explicit `CASE` + `two_stage` + 9dp Snapshot Test + `LOAD_SQL` 5-Column `INSERT`s):** Specified explicit SQL `CASE` expressions for $\alpha(\rho_P)$ and $g(x)$, added `two_stage=False` for `legacy_step_15`, updated the pre-edit snapshot step to use `uv run python scripts/make_fixtures.py`, named both `INSERT INTO genre_map` statements in `pipeline/genre.py:19–30` (`lines 21–23` CSV `INSERT` and `lines 24–29` year/decade `INSERT` taking `false` as its 5th column), defined the 5-column `is_umbrella` rule for `scripts/make_fixtures.py:936–939`, and consolidated `test_generate_fixture_marts_rng_parity` into Packet 2 only.
- **Section 4 Risk 2 (`genre_xray.json` Size):** Marked the real-data `1.5–2.5 MB uncompressed (~350 KB gzipped)` payload figure as an explicit **`[UNVERIFIED ESTIMATE]`** with its row-count and bytes-per-row basis (~18k–25k 4-tuples $\times$ ~100–120 B/row).

---

## 4. Remaining Risks Not Resolvable from Plan or Fixture Alone

1. **Real-Data Tag Distribution on Owner's Mac:** Because `dev_fixtures.duckdb` assigns one synthetic genre per artist, the real-world share of tracks that remain on `style = parent_genre` after disaggregation depends on the tag density in `build/music.duckdb` and will only be observed when `uv run python -m pipeline.genre sensitivity` and `unmapped --top 200` run on the owner's Mac.
2. **Real `genre_xray.json` Payload Size (`[UNVERIFIED ESTIMATE]`):** Fixture `genre_xray.json` is estimated at ~1,500 rows (~180 KB), and real-data `genre_xray.json` is an **`[UNVERIFIED ESTIMATE]`** of ~1.5–2.5 MB uncompressed (~350 KB gzipped), based on an estimated ~18k–25k classified 4-tuple rows at ~100–120 bytes/row JSON. While well below the 25 MiB Cloudflare Workers asset limit, actual byte size must be measured during the real `SITE_DB=build/music.duckdb` build.
