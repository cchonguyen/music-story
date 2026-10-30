# music-story: Beyond-Wrapped Visual Insights, Fetch Optimizations & Adversarial Hardening Plan

Elevate `music-story` far beyond standard Last.fm and Spotify Wrapped summaries by unlocking **five already-collected but unused telemetry dimensions** in `sql/schema.sql` (`enr_deezer_track.bpm`/`gain`, post-binge survival trajectories, `plays.shuffle`/`reason_start`/`completion_ratio`, `dim_artist.lastfm_listeners`/`begin_year`, and `dim_artist.country`), pairing them with **four high-leverage data fetch and pipeline optimizations** and a live Observable Framework runtime on `0.0.0.0:3000`.

---

## User Review & Critical Decisions

> [!IMPORTANT]
> Review the augmented visual insights, architectural trade-offs, and fetch optimizations below. Click **Proceed** on this plan to execute the pipeline optimizations, chapter visual upgrades, and port `3000` dev server setup.

- **Confirmed Baseline Architecture**: Keep **Observable Framework** on `0.0.0.0:3000`, preserve all existing `sql/schema.sql` and `tests/test_site_pages.py` contracts, lock the three genre parent mappings (`blues -> jazz`, `hardcore -> metal`, `reggae/dub/ska -> world`), and normalize `ios` / `iphone` / `ipad` platforms case-insensitively.
- **Recommended Organization Strategy (Best Fit)**: **Weave each new visual directly into its thematic chapter AND expose all unlocked dimensions inside the Explorer Remix Studio.**
  - *Why this works best*: Keeping chapters cohesive around a narrative domain (`Artists`, `Songs`, `Genres`, `Habits`, `Places`) gives guided storytelling on first read, while upgrading `Explorer` with the same enriched columns lets you cross-filter any combination on demand without cluttering the sidebar.

---

## 1. Overview & Core Concept

- **What It Does**: Transforms 19.5 years of personal listening telemetry (Last.fm 2007–2026 and Spotify 2011–2026) into an epistemically transparent, deeply personal interactive story and visual laboratory.
- **Why Standard Wrapped Falls Short**: Spotify Wrapped and Last.fm reports reduce listening to top-N vanity lists and raw volume counters. They ignore *how* you listen (hand-picked vs. shuffle autopilot, 5-second skip impatience vs. deep completion), *what happens after an obsession* (burnout vs. lifelong canonization), *where the music comes from* (artist origin vs. your travel), and *how coverage shifts distort multi-decade trends*.
- **Zero-Hallucination Guarantee**: Every new insight below is computed strictly from deterministic columns already present in `sql/schema.sql` and `scripts/make_fixtures.py`—never inventing synthetic scores or ungrounded claims.

---

## 2. User Experience & Creative Visual Library ("Beyond Wrapped")

### A. Thematic Chapter Upgrades & New Visual Insights

#### 1. `Overview` (`index.md`) — Macro Era Regimes & Discovery Velocity
- **Coverage-Aware Volume & Regime Overlays**: Vertical structural markers separate the **Last.fm-Only Era (2007–2010)**, **Spotify Onboarding & Split Era (2011–2021)**, and **Matched Dual-Source Era (2022–2026)**.
- **Discovery Velocity Lens (Interactive Toggle)**: Switch between **Raw Annual Plays/Hours**, **True Discovery Rate (New Artists & New Tracks per 1,000 Plays)**—which strips out logging volume spikes to show when your curiosity actually peaked—and **Plays vs. Skips Stacked Volume**.

#### 2. `Artists` (`artists.md`) — Lifelines Matrix, Underground Index & Vanguard Score
- **Artist Lifelines Matrix (Year $\times$ Artist Horizon Grid)**: Replaces static tables of `first_year` and `last_year` with a 20-year heatmap matrix filterable by archetype:
  - *Staples* ($\ge 10$ active years: continuous multi-decade backbones).
  - *Comebacks* ($\ge 3$-year hiatus before returning: dormant rediscoveries).
  - *Flashes* (1 active year with $\ge 50$ plays: intense single-year eras).
- **NEW — The Underground / Obscurity Index (`dim_artist.lastfm_listeners`)**:
  - Uses global Last.fm listener counts already stored in `dim_artist` to classify every play into popularity tiers: **Deep Underground (`<25k`)**, **Indie / Niche (`25k–150k`)**, **Mid-Tier (`150k–750k`)**, and **Global Mainstream (`750k+`)**.
  - Plots your **Mainstream vs. Underground Drift** over 19.5 years and highlights **"Vanguard / Early-Adopter" Artists** where your first listen (`first_year`) occurred within $0\text{–}2$ years of the artist's career `begin_year` (`dim_artist.begin_year`).
- **Remixer Dual-Bar Comparison**: Visualizes remix plays alongside plays of the original compositions (`mart_remixer_year`).

#### 3. `Songs` (`songs.md`) — Earworm Half-Life & The Nostalgia Matrix
- **NEW — The Earworm Half-Life: Burnout vs. Canonization (`mart_binge` + post-window survival)**:
  - Goes beyond listing 14-day binges by plotting `window_plays` / `rate_ratio` against **Post-Binge Survival Share** (`(lifetime_plays - window_plays) / lifetime_plays` and post-window persistence):
    - **Flash Burnouts ("Overplayed to Death")**: Songs where $>65\%$ of all lifetime plays happened inside a single 14-day frenzy, then vanished.
    - **Canonized Anthems ("Love at First Binge")**: Songs triggered by a 14-day obsession that went on to accumulate $3\times\text{–}10\times$ more plays across subsequent years.
- **Song Age & Nostalgia Lens (`mart_song_age`)**: Toggle between **Absolute Plays** and **100% Normalized Catalog Share** (with an explicit toggle for `unknown` release years) to reveal whether each year of your life favored brand-new releases (`age = 0`) or deep catalog nostalgia (`11–20` and `21+` years old).

#### 4. `Genres` (`genres.md`) — Epistemically Honest Genre Streams & Style Anatomy
- **Unclassified / Enrichment Coverage Band Toggle**: Cross-references `mart_genre_year` against `mart_year.plays` so you can toggle between **Classified Genres Only (100% Share)**, **Share of All Plays (Including Unclassified Band)**, and **Weighted Play Counts**.
- **Style Drilldown**: Select any parent genre (`electronic`, `rock`, `pop`, `hip hop`, `jazz`, `metal`, `world`, etc.) to inspect how specific sub-styles (`electro house`, `dubstep`, `house`, `techno`, `ambient`, `k-pop`, `v-pop`, `j-pop`) rose and fell within that parent.

#### 5. `Habits` (`habits.md`) — Intentionality vs. Autopilot, Circadian BPM & Session Sensitivity
- **NEW — Intentionality vs. Algorithmic Autopilot (`plays.shuffle`, `reason_start`, `reason_end`)**:
  - Uses Spotify behavioral flags already in `plays` and `skips` to contrast **Deliberate Hand-Picked Plays** (`reason_start = 'clickrow'`, `shuffle = false`) against **Passive Flow / Shuffle Autopilot** (`reason_start = 'trackdone'`, `shuffle = true`).
  - **The Patience & Skip Survival Curve**: Breaks down skip behavior by elapsed seconds before hitting `fwdbtn` (`0–5s` instant rejection vs. `6–15s` intro check vs. `16–29s` mid-track bailout) alongside full-listen completion ratios.
- **NEW — Circadian Tempo Heartbeat (`enr_deezer_track.bpm` & `gain`)**:
  - Joins octave-corrected Deezer BPM (`bpm > 175` halved to fix double-tempo beat-detector artifacts) with `started_at_local` hour and `session_index` to show how your average **BPM & Audio Energy** shift from morning (`07:00–11:00`) to afternoon (`12:00–17:00`) to late night (`22:00–03:00`).
- **Session Gap Sensitivity Overlay (`10m` vs. `20m` vs. `30m`)**: Displays `sessions_10`, `sessions` (20m baseline), and `sessions_30` from `mart_sessions_year` so you can see how sensitive session counts are to the inactivity threshold.

#### 6. `Places` (`places.md`) — Physical Footprint vs. Musical Passport
- **Direct vs. Imputed Location Provenance**: Toggle `mart_country_year` between **Top Countries**, **Direct vs. Imputed Country Breakdown (`imputed_plays`)**, and **Unknown (`ZZ`) Location Share**.
- **NEW — Musical Passport (`dim_artist.country` vs. `plays.country`)**:
  - Compares **where you were physically listening** (`US`, `JP`, `FR`, `CA`) against **where the artists you listened to originate** (`US`, `GB`, `DE`, `KR`, `JP`, `VN`), highlighting whether international trips coincide with spikes in local artists from that region.

#### 7. `Explorer` (`explorer.md`) — Multi-View Remix Studio
- **Interactive Dimension Slicers**: Search input (matching both display names and normalized ASCII keys), From/To Year range, Parent Genre filter, Event filter (`Plays Only`, `Plays + Skips`, `Skips Only`), and Group By dimension (`Track`, `Artist`, `Album`, `Style`, `Year`, `Platform`, `Country`).
- **Switchable Visual Pivot Canvas**:
  1. **Monthly Timeline Pulse**: Interactive bar/area timeline of the active slice.
  2. **Visual Pivot Selector**: Switch between a **Slice Rhythm Heatmap (Weekday $\times$ Hour)** for the active search/genre slice, a **Top 15 Ranked Horizontal Bar Chart**, or an **Intentionality & Skip Rate Breakdown**.
  3. **500-Row Tabular Telemetry Grid**: Right-aligned `tabular-nums` metrics (`plays`, `hours`, `skips`, `skip_rate`, `first_play`, `last_play`).

---

## 3. Data Pipeline, Fetch & Architecture Optimizations (Options & Recommendations)

### Optimization 1: Stretching the 500/Day Spotify Quota (`pipeline/enrich_queue.py`)
- **The Problem**: 3,151 songs in your history span multiple Spotify URIs (~33% of plays—e.g. album version, single, compilation re-issue). Currently, `("spotify", "tracks")` queues every `track_uri` purely by URI play count. That means Spotify's 500/day budget is spent fetching 2nd and 3rd URIs for popular songs whose primary URI is *already* fetched, starving unique un-enriched songs further down the curve.
- **Options Considered**:
  - *Option A (Current)*: Rank strictly by `track_uri` play count. Simple, but wastes ~15–25% of daily quota on duplicate recordings of already-enriched songs.
  - *Option B (Recommended — Primary-URI-First Stratification)*: Partition `events` by `(artist_norm, full_norm)` so each unique song's **#1 most-played `track_uri`** gets ranked in Tier 1 (ordered by the song's total play count), while secondary/twin URIs for that same song are placed in Tier 2 (after unique songs within the cover target).
- **Why Option B Wins**: Reaches **80%+ unique song and play coverage thousands of requests sooner** without dropping secondary URIs (which still sit in the queue if you ever want 100% URI parity).

### Optimization 2: Pruning Redundant Tail Searches (`pipeline/enrich_queue.py`)
- **The Problem**: `spotify_tail` queues `(artist_norm, full_norm)` keys past the Spotify cap for `musicbrainz.search` (`1.05s/req`) and `deezer.search` (`0.11s/req`) without checking whether that key *already* resolved an ISRC via Last.fm `track_mbid` (`enr_mb_recording`) or another URI in `enr_spotify_track`.
- **Recommended Fix**: Add an `ANTI JOIN` in `spotify_tail()` against keys already resolved in `enr_spotify_track` (status 200 with ISRC) or `enr_mb_recording` (status 200 with non-empty `isrcs`). Cuts redundant tail network traffic immediately.

### Optimization 3: Zero-Cost Telemetry Propagation (`sql/marts/` & `pipeline/site_data.py`)
- **The Problem**: `enr_deezer_track` (`bpm`, `gain`), `dim_artist` (`country`, `begin_year`, `lastfm_listeners`), and `plays` (`shuffle`, `reason_start`, `reason_end`, `completion_ratio`) are already populated in DuckDB by Steps 01–05, yet dropped at Step 07 (`sql/marts/`).
- **Recommended Fix**:
  - Add octave-cleaned BPM (`CASE WHEN bpm > 175 THEN bpm / 2.0 WHEN bpm < 55 AND bpm > 0 THEN bpm * 2.0 ELSE bpm END`) and behavioral/origin summaries while **preserving every existing column and table name** in `10_simple.sql`..`40_explorer.sql` so all existing pytest assertions (`test_marts_simple_fixture.py`, `test_marts_trap_fixture.py`, `test_site_data.py`, `test_site_pages.py`) pass without regression.

### Optimization 4: Single-Pass Mart Caching & Port 3000 Dev Server (`pipeline/site_data.py`)
- **The Problem**: Running `observable build` or `observable preview` executes 16 `.sh` loaders in `site/src/data/`. In fixture mode, `fixture_marts()` rebuilds all 15 marts in memory **16 separate times**, and in container environments without `uv`, the `.sh` loaders fail to start the dev server.
- **Recommended Fix**:
  - Cache materialized mart outputs in `build/marts_cache/` (invalidated automatically if SQL marts or the DB timestamp change) and wire `/usr/local/bin/uv` + root `package.json` so `npm run dev` serves Observable Framework on `0.0.0.0:3000` in under 2 seconds.

---

## 4. Technical Architecture & Data Strategy

```
┌────────────────────────────────────────────────────────────────────────────┐
│                   ENRICHMENT & QUEUE OPTIMIZATION LAYER                    │
│  • Primary-URI-First Spotify Ranking (stretches 500/day budget by ~20%)    │
│  • Cross-Source ISRC Anti-Join Pruning for Deezer / MusicBrainz Tail       │
└─────────────────────────────────────┬──────────────────────────────────────┘
                                      │
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                   DUCKDB PIPELINE & SINGLE-PASS MART CACHE                 │
│  • Existing 15 Marts (100% backwards-compatible with pytest suite)         │
│  • Unlocked Telemetry Columns:                                             │
│    - Octave-Corrected BPM & Gain (enr_deezer_track)                        │
│    - Artist Country, Begin Year & Global Listeners (dim_artist)            │
│    - Shuffle, Reason Start/End & Completion Ratio (plays / skips)          │
│    - Post-Binge Survival Share (mart_binge + lifetime persistence)         │
└──────────────────────┬─────────────────────────────────────┬───────────────┘
                       │                                     │
         JSON Loaders (site/src/data/*.json.sh)    Parquet Loader (.parquet.sh)
                       │                                     │
                       ▼                                     ▼
┌─────────────────────────────────────────────┐ ┌────────────────────────────┐
│   OBSERVABLE FRAMEWORK CHAPTERS (:3000)     │ │   EXPLORER REMIX STUDIO    │
│  • Overview: Era Regimes & Discovery Rate   │ │  • Search & Normalized SQL │
│  • Artists: Lifelines + Underground Index   │ │  • Year / Genre / Skip /   │
│  • Songs: Earworm Half-Life + Song Age      │ │    Intent Slicers          │
│  • Genres: Unclassified Coverage Toggle     │ │  • Monthly Pulse + Rhythm  │
│  • Habits: Intentionality, BPM & 10/20/30m  │ │    Heatmap + Top Bar Pivot │
│  • Places: Direct/Imputed + Artist Passport │ │  • 500-Row Tabular Grid    │
└─────────────────────────────────────────────┘ └────────────────────────────┘
```
