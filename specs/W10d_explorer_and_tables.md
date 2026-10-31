# W10d — DuckDB-Wasm Explorer Subfilters & Synchronized Chapter Data Tables

## Goal
Upgrade `site/src/explorer.md` with multi-facet subfilters and a DuckDB-Wasm `LEFT JOIN` against `genre_xray.json`, and pair every chart section across `index.md`, `artists.md`, `songs.md`, `habits.md`, and `places.md` with synchronized `Inputs.table` views.

## Contracts

### 1. DuckDB-Wasm Explorer (`site/src/explorer.md`)
- Loads `FileAttachment("data/plays_explorer.parquet")` and `FileAttachment("data/genre_xray.json")` into DuckDB-Wasm.
- Registers `xray` table in DuckDB-Wasm and creates view `plays_xray` via:
  ```sql
  CREATE VIEW plays_xray AS
  SELECT p.*,
         x.primary_weight,
         x.level AS genre_level,
         x.secondary_styles,
         x.suppressed_umbrellas
  FROM plays p
  LEFT JOIN xray x USING (artist_norm, title_norm, parent_genre, style)
  ```
- Asserts in-browser that `postJoinPlays === preJoinPlays` and `unmatchedClassifiedPlays === 0`.
- Reports `Classified Plays` and `Unclassified Plays (no genre tags)` explicitly in KPI cards so unclassified rows are never silently dropped.
- Multi-facet subfilters: Search, From/To Year, Parent Genre, Sub-Style, Daypart (`All Hours`, `Night 00–05`, `Morning 06–11`, `Afternoon 12–17`, `Evening 18–23`), Day Type (`All Days`, `Weekdays`, `Weekends`), Country, Platform, Tag Level, and Group By (`Track (with Genre X-Ray)`, `Artist`, `Album`, `Style`, `Year`, `Platform`, `Country`, `Local Hour`).

### 2. Synchronized Chapter Tables (`site/src/*.md`)
- `site/src/index.md`: Year range filter + synchronized annual summary table (`year`, `plays`, `skips`, `listen_hours`, `artists`, `tracks`, `new_artists`, `new_tracks`, `sessions`) and circadian weekday $\times$ hour summary table. Preserves `<!-- story: overview narrative -->`.
- `site/src/artists.md`: Synchronized `Inputs.table` for the Obscurity Index by year & tier (`obscurityYear`), alongside existing Top 10, Lifelines (`Staples`, `Comebacks`, `Flashes`), Vanguard, and Remixers tables. Preserves `<!-- story: top artists -->` and `<!-- story: arcs -->`.
- `site/src/songs.md`: Synchronized `Inputs.table` for Song Age by year & bucket (`filteredAge`), alongside existing Top Tracks and Earworm Half-Life tables. Preserves `<!-- story: top tracks -->` and `<!-- story: binges -->`.
- `site/src/habits.md`: Synchronized `Inputs.table` views for Weekday & Hour rhythm, Sessions & Gap Threshold Sensitivity (`10m` / `20m` / `30m`), Intentionality & Skip Timing (`intentSkip`), Circadian BPM Heartbeat (`tempoRows`), Skip Rate (`skip`), and Platform Share (`platform`). Preserves `<!-- story: weekly rhythm -->`.
- `site/src/places.md`: Synchronized `Inputs.table` views for Country & Imputation Provenance (`known`), Musical Passport Artist Origins (`artistOriginRows`), Travel Resonance (`travelRows`), and Unknown Location (`unknown`). Preserves `<!-- story: places -->`.
