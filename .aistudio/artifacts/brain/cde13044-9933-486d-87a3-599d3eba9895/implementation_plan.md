# music-story: Beyond-Wrapped Visual Library, Fetch Optimizations & Epistemic Hardening Plan

Transform 19.5 years of personal listening telemetry (Last.fm 2007–2026 and Spotify 2011–2026) into an epistemically rigorous, deeply personal Observable Framework story and interactive visual studio on port `3000`—unlocking five already-collected schema dimensions, four high-leverage fetch and pipeline optimizations, and a multi-view Explorer Remix Studio.

---

## User Review & Critical Decisions

> [!IMPORTANT]
> All visual, statistical, and architectural choices from both rounds of review have been confirmed below. Click **Proceed** to execute the pipeline optimizations, chapter visual upgrades, and Observable Framework server setup.

- **Confirmed Decision 1 — Frontend & Site Organization**:
  - Keep **Observable Framework** on `0.0.0.0:3000` as the interactive narrative runtime.
  - **Weave each new visual insight directly into its thematic chapter** (`Overview`, `Artists`, `Songs`, `Genres`, `Habits`, `Places`) **AND add a dedicated Insights / Visual Remix tab system inside `Explorer`** so every unlocked dimension can be cross-filtered on demand.
- **Confirmed Decision 2 — Five New "Beyond-Wrapped" Non-Hallucinated Visual Insights**:
  1. **Earworm Half-Life (`Songs`)**: Post-binge survival trajectories distinguishing **Flash Burnouts** ("Overplayed to Death" within 14 days) from **Canonized Anthems** ("Love at First Binge" that stay in multi-year rotation).
  2. **Intentionality vs. Shuffle Autopilot & Skip Survival Curve (`Habits`)**: Contrasting hand-picked plays (`reason_start = 'clickrow'`, `shuffle = false`) against passive shuffle (`shuffle = true`), paired with an elapsed-time **Skip Survival & Impatience Curve** (`0–5s` instant rejection vs. `6–15s` intro check vs. `16–29s` bailout).
  3. **Circadian BPM Heartbeat & Session Energy Arc (`Habits`)**: Using octave-cleaned Deezer `bpm` and `gain` (`enr_deezer_track`) to map tempo and audio energy across the 24-hour clock and across `session_index` (`1 = opener` $\to$ middle $\to$ closer).
  4. **Underground Obscurity Index & Early-Adopter Vanguard (`Artists`)**: Using `dim_artist.lastfm_listeners` and `dim_artist.begin_year` to plot your 19.5-year drift across global popularity tiers (`<25k Deep Underground` to `750k+ Global Mainstream`) and surface **Vanguard Artists** discovered within $0\text{–}2$ years of their career start.
  5. **Musical Passport: Artist Origin vs. Physical Travel (`Places`)**: Comparing `dim_artist.country` (MusicBrainz artist origin: `US`, `GB`, `KR`, `VN`, `JP`, `DE`, `FR`...) against `plays.country` (your physical location and international trips).
- **Confirmed Decision 3 — Four Data Fetch & Pipeline Optimizations**:
  1. **Primary-URI-First Spotify Queue Ranking**: Partition by `(artist_norm, full_norm)` so each unique song's top URI is fetched in Tier 1 before secondary/compilation twin URIs, stretching the 500/day Spotify budget by ~20%.
  2. **Cross-Source ISRC Tail Pruning**: Filter `spotify_tail` with an `ANTI JOIN` against keys that already resolved an ISRC via `enr_spotify_track` or `enr_mb_recording` (`track_mbid`), eliminating thousands of redundant MusicBrainz and Deezer searches.
  3. **Zero-Cost Telemetry Propagation**: Expose octave-corrected Deezer `bpm`/`gain`, artist `country`/`begin_year`/`lastfm_listeners`, and play `shuffle`/`reason_start`/`completion_ratio` in the marts and `explorer_plays` without breaking any existing schema contracts.
  4. **Single-Pass Mart Caching**: Materialize and cache mart outputs in a single pass so `observable build` and `observable preview` serve all 16 `.sh` loaders in milliseconds instead of rebuilding all marts 16 separate times.
- **Confirmed Decision 4 — Epistemic Overlays & Taxonomy Fixes**:
  - Include **Era Regime Overlays** (`2007–2010 Last.fm Only`, `2011–2021 Spotify Onboarding`, `2022–2026 Matched Twin Era`), **Unclassified Genre Coverage Toggles**, **10m / 20m / 30m Session Gap Sensitivity Lines**, **Direct vs. Imputed Country Toggles**, **Case-Insensitive iOS/iPhone/iPad Normalization**, and lock `blues -> jazz`, `hardcore -> metal`, `reggae/dub/ska -> world`.

---

## 1. Overview & Core Concept

- **What It Does**: Synthesizes 19.5 years of personal listening telemetry into an interactive 7-chapter story and browser-resident SQL/Parquet laboratory.
- **Target Audience / Persona**: Designed for deep personal musical archaeology—going beyond static top-10 lists to uncover behavioral rhythms, obsession half-lives, sonic tempo curves, cultural geography, and the boundary between genuine taste shifts and logging coverage artifacts.
- **Key Value**: Every insight is 100% grounded in deterministic telemetry already captured by your pipeline (`sql/schema.sql`), surfacing rich dimensions that were previously stranded in staging and enrichment tables while cutting API tail fetch times and site build overhead.

---

## 2. User Experience & Visual Design

### Chapter-by-Chapter User Flows & Visual Library

1. **Overview (`index.md`) — Macro Era Regimes & Discovery Velocity**
   - **Interactive Lens Selector**: Switch between **Raw Volume (`Plays` & `Hours`)**, **Normalized Discovery Rate (`New Artists` & `New Tracks` per 1,000 Plays)**, and **Plays vs. Skips Stacked Volume**.
   - **Coverage Regime Annotations**: Vertical rules and subtle shaded bands mark the 2011 Spotify transition and 2022 dual-source era so volume jumps are contextualized immediately.
   - **Circadian Rhythm Overview**: 7-day $\times$ 24-hour listening density grid with summary KPI callouts.

2. **Artists (`artists.md`) — Lifelines Matrix, Underground Index & Vanguard Discovery**
   - **Artist Lifelines Matrix (Year $\times$ Artist Horizon Grid)**: Interactive cohort switcher (*Staples $\ge 10$ yrs*, *Comebacks $\ge 3$ yr gap*, *Flashes 1 yr $\ge 50$ plays*, *Top 25 Overall*) rendering a 20-year cell matrix colored by annual play intensity and peak share.
   - **The Underground Obscurity Index & Early-Adopter Vanguard**:
     - Stacked area/bar breakdown of annual plays by global Last.fm listener tier (*Deep Underground `<25k`*, *Indie/Niche `25k–150k`*, *Mid-Tier `150k–750k`*, *Mainstream `750k+`*).
     - **Vanguard Table & Scatter**: Highlights artists where `first_play_year - begin_year <= 2`, pairing global listener count with personal lifetime plays.
   - **Remixer Dual-Bar Comparison**: Visual side-by-side comparison of `remix_plays` vs. `original_plays` per remixer.

3. **Songs (`songs.md`) — Earworm Half-Life & Musical Biological Clock**
   - **Earworm Half-Life: Burnout vs. Canonization**:
     - Interactive scatter plot (`Plot.dot`) mapping 14-day burst intensity (`rate_ratio` & `window_plays`) against **Post-Binge Survival Share** (`post_binge_plays / lifetime_plays`), visually separating **Flash Burnouts** (consumed in one 14-day fever and abandoned) from **Canonized Anthems** (obsessions that became multi-year staples).
   - **Song Age & Nostalgia Lens**: Toggle between **Absolute Plays** and **100% Normalized Share** (plus an `Include Unknown Release Year` switch) to track whether listening favors new releases (`0` and `1–2` years old) or catalog nostalgia (`11–20` and `21+` years).

4. **Genres (`genres.md`) — Coverage-Aware Genre Streams & Style Anatomy**
   - **Epistemic Coverage Toggle**: Switch between **Classified Genres (100% Normalized)**, **Share of All Plays (Including Unclassified Residual)**, and **Weighted Play Counts**, computed by comparing summed `mart_genre_year` weights against `mart_year.plays`.
   - **Style Drilldown**: Pick any parent genre to inspect its constituent styles as either a stacked stream or 100% normalized share over time.

5. **Habits (`habits.md`) — Intentionality, Circadian BPM Heartbeat & Session Sensitivity**
   - **Intentionality vs. Algorithmic Autopilot**:
     - Annual and hourly breakdown of **Deliberate Selection** (`reason_start = 'clickrow'`, unshuffled) vs. **Organic Album/Playlist Flow** (`trackdone`, unshuffled) vs. **Shuffle Autopilot** (`shuffle = true`).
     - **Skip Survival & Impatience Curve**: Distribution of skip timestamps (`0–5s` instant skip, `6–15s` intro sample, `16–29s` verse bailout) alongside full-track completion ratios.
   - **Circadian BPM Heartbeat & Session Energy Arc**:
     - Plots octave-corrected **Tempo (BPM)** and **Loudness Gain (dB)** across the 24-hour clock (`00:00–23:00`) and across session depth (`Opener #1` $\to$ `Tracks 2–5` $\to$ `Tracks 6–10` $\to$ `Deep Session 11+`).
   - **Session Gap Sensitivity Overlay**: Interactive toggle comparing `10-minute`, `20-minute (baseline)`, and `30-minute` session counts (`sessions_10`, `sessions`, `sessions_30`) alongside median and P90 session length curves.

6. **Places (`places.md`) — Physical Footprint vs. Musical Passport**
   - **Location Provenance Toggle**: Switch between **Top Known Countries**, **Direct vs. Imputed Country Breakdown (`imputed_plays`)**, and **Unknown (`ZZ`) Location Volume**.
   - **Musical Passport (Artist Origin vs. Listener Location)**: Tracks annual share of plays by **Artist Home Country** (`dim_artist.country`: `US`, `GB`, `KR`, `VN`, `JP`, `DE`, `FR`...) and highlights **Travel Resonance** during international trips (`JP` Apr 2023, `FR` Jun 2024, `CA` Feb 2025).

7. **Explorer (`explorer.md`) — Multi-Tab Insights & Visual Remix Studio**
   - **Slicer Bar**: Search text (display + normalized), From/To Year range, Parent Genre filter, Event filter (`Plays Only`, `Plays + Skips`, `Skips Only`), Intent filter (`All`, `Hand-Picked Only`, `Shuffle Only`), and Group By dimension (`Track`, `Artist`, `Album`, `Style`, `Year`, `Platform`, `Country`, `Artist Origin`).
   - **Dedicated Insights / Remix Tabs**:
     - *Tab 1 — Timeline & Rhythm Pulse*: Monthly play/skip timeline paired with a live **Weekday $\times$ Hour Rhythm Heatmap** for the active slice.
     - *Tab 2 — Top Entities & Intentionality Rank*: Horizontal ranked bar chart of top 15 grouped items colored by skip rate or shuffle share.
     - *Tab 3 — Sonic & Obscurity Scatter*: Interactive plot of BPM vs. Last.fm Obscurity / Completion Ratio for the active slice.
   - **500-Row Tabular Telemetry Grid**: Full sortable table with `tabular-nums` alignment.

### Visual Identity & Theme

- **Aesthetic Direction**: Clean **Editorial Data Journalism**—crisp structural hairlines, generous breathing room, zero decorative status badges, and high-signal Observable Plot typography.
- **Color & Contrast Discipline**:
  - **60-30-10 Balance**: Neutral editorial canvas, 1px hairline dividers, and intentional categorical/sequential palettes (`YlGnBu` for rhythm matrices, `Turbo`/`Viridis` for tempo/intensity, `Tableau10` for genres, and `#94a3b8` neutral slate strictly for `unknown` / `unclassified` uncertainty bands).
- **Typography & Tabular Numerals**:
  - Enforces `font-variant-numeric: tabular-nums` across all tables, metric strips, and axis labels; zero code-comment headers or pill-badge clutter.

---

## 3. Key Product & Architectural Decisions

- **Decision 1: Primary-URI-First Spotify Queue Ranking (`pipeline/enrich_queue.py`)**
  - *Chosen Approach*: Partition `events` by `(artist_norm, full_norm)` so the most-played `track_uri` of each unique song is queued in Tier 1 (ordered by total song plays), while secondary URIs of that same song are queued in Tier 2.
  - *Why*: Prevents multi-URI songs (~33% of plays) from consuming multiple slots of the 500/day Spotify quota before un-enriched unique songs are reached.
- **Decision 2: Cross-Source ISRC Tail Pruning (`pipeline/enrich_queue.py`)**
  - *Chosen Approach*: Exclude `(artist_norm, full_norm)` keys from `spotify_tail()` when an ISRC is already present in `enr_spotify_track` (via another URI) or `enr_mb_recording` (via `track_mbid`).
  - *Why*: Saves thousands of unnecessary MusicBrainz (`1.05s/req`) and Deezer (`0.11s/req`) tail search requests.
- **Decision 3: Backwards-Compatible Mart Enrichment (`sql/marts/` & `pipeline/site_data.py`)**
  - *Chosen Approach*: Keep all 15 existing mart table names and required columns intact while appending derived columns (or enriching `mart_binge`, `mart_artist_arc`, `mart_clock`, `mart_country_year`, `mart_sessions_year`, and `explorer_plays`) so every existing test in `tests/` continues to pass.
- **Decision 4: Single-Pass Mart Caching & Port 3000 Dev Server**
  - *Chosen Approach*: Materialize and cache mart JSON/Parquet outputs in a single pass and wire root `package.json` + `/usr/local/bin/uv` so `npm run dev` serves Observable Framework on `0.0.0.0:3000`.

---

## 4. Technical Architecture & Data Strategy

```
┌────────────────────────────────────────────────────────────────────────────┐
│                   ENRICHMENT & QUEUE OPTIMIZATION LAYER                    │
│  • Primary-URI-First Spotify Ranking (Tier 1 unique songs, Tier 2 twins)   │
│  • Cross-Source ISRC Anti-Join Pruning for Deezer / MusicBrainz Tail       │
└─────────────────────────────────────┬──────────────────────────────────────┘
                                      │
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                   DUCKDB PIPELINE & SINGLE-PASS MART CACHE                 │
│  • Core 15 Marts + Explorer View (100% backwards-compatible with pytest)   │
│  • Unlocked Schema Signals:                                                │
│    - Octave-Corrected BPM & Gain (enr_deezer_track)                        │
│    - Artist Country, Begin Year & Global Listeners (dim_artist)            │
│    - Shuffle, Reason Start/End & Completion Ratio (plays / skips)          │
│    - Post-Binge Survival Share & Archetype (mart_binge + plays)            │
└──────────────────────┬─────────────────────────────────────┬───────────────┘
                       │                                     │
         JSON Loaders (site/src/data/*.json.sh)    Parquet Loader (.parquet.sh)
                       │                                     │
                       ▼                                     ▼
┌─────────────────────────────────────────────┐ ┌────────────────────────────┐
│   OBSERVABLE FRAMEWORK CHAPTERS (:3000)     │ │   EXPLORER REMIX STUDIO    │
│  • Overview: Era Regimes & Discovery Rate   │ │  • Slicers: Search, Year,  │
│  • Artists: Lifelines + Underground Index   │ │    Genre, Skip, Intent     │
│  • Songs: Earworm Half-Life + Song Age      │ │  • Tab 1: Timeline +       │
│  • Genres: Unclassified Coverage Toggle     │ │    Slice Rhythm Heatmap    │
│  • Habits: Intentionality, BPM & 10/20/30m  │ │  • Tab 2: Top 15 & Intent  │
│  • Places: Direct/Imputed + Artist Passport │ │  • Tab 3: Sonic Scatter    │
└─────────────────────────────────────────────┘ └────────────────────────────┘
```

### Interactive Component & State Mapping

- **Overview (`index.md`)**: Metric lens radio (`Plays & Era Regimes`, `Discovery Velocity per 1k Plays`, `Plays vs. Skips`) dynamically updates the primary `Plot` marks and regime callouts.
- **Artists (`artists.md`)**: Year selector for Top 10 bars + table; Lifelines cohort selector (`Staples`, `Comebacks`, `Flashes`, `Top 25 Overall`); Underground Obscurity mode selector (`Share of Plays by Listener Tier`, `Early-Adopter Vanguard Artists`).
- **Songs (`songs.md`)**: Year selector for Top Tracks; Earworm Half-Life archetype filter (`All Binges`, `Canonized Anthems`, `Flash Burnouts`); Song Age normalization toggle (`Absolute Plays` vs. `100% Share` + `Include Unknown`).
- **Genres (`genres.md`)**: Coverage mode toggle (`Classified Only (100%)`, `Include Unclassified Residual`, `Weighted Plays`) + Parent Genre drilldown selector.
- **Habits (`habits.md`)**: Weekday $\times$ Hour year picker; Intentionality & Skip lens (`Curation vs. Shuffle Autopilot`, `Skip Survival & Impatience Curve`); Circadian BPM lens (`BPM by Hour of Day`, `BPM & Energy by Session Depth`); Session sensitivity toggle (`10m / 20m / 30m Gap Comparison`).
- **Places (`places.md`)**: Location provenance toggle (`Top Known Countries`, `Direct vs. Imputed Share`) + Musical Passport view (`Artist Origin Country over Time`, `Travel Resonance`).
- **Explorer (`explorer.md`)**: Search input, From/To Year selectors, Parent Genre selector, Event Type selector, Intent filter, Group By selector, and Insights/Remix Tab switcher (`Timeline & Slice Rhythm Heatmap`, `Top 15 Ranked Comparison`, `Sonic & Obscurity Scatter`).
