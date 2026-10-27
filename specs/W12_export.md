# W12: privacy export

Tier: Haiku (done by the lead). Deliverables: `sql/08_export.sql`, `pipeline/export.py`,
`site/src/data/plays_explorer.parquet.sh`, `tests/test_export_fixture.py`. Never deploy.

## Why
The explorer page (plan: "lazy-loads DuckDB-Wasm over one Zstd `plays_explorer.parquet`") needs
row-level plays, which the aggregate marts do not carry. Row-level data is the riskiest thing the
site ships, so it passes a privacy gate first.

## Privacy gate
- Incognito plays are dropped. Videos and podcasts never reach `plays` (W1 keeps music URIs only).
- No timestamps: time is coarsened to local date, hour (0-23) and ISO weekday (1 = Monday).
- No ids that encode order (`play_id`, `session_id`, `sp_id`), no IP (never loaded), no raw
  platform strings, no match diagnostics.
- Skips are not exported; `mart_skip_rate` covers them.

## Table `export_plays` (built by step 08, not in schema.sql: like marts, it is derived output)
| column | type | from |
|---|---|---|
| local_date | DATE | `started_at_local` |
| year | SMALLINT | |
| hour | TINYINT | |
| weekday | TINYINT | ISO, 1 = Monday |
| artist | VARCHAR | `dim_artist.name` (primary artist) |
| track | VARCHAR | `dim_track.title` |
| album | VARCHAR | `dim_album.name`, NULL when unknown |
| parent_genre | VARCHAR | highest-weight `track_genre` row, ties by name; NULL when untagged |
| style | VARCHAR | same row |
| release_year | SMALLINT | `dim_track.recording_year` |
| seconds | INTEGER | `round(ms_imputed / 1000)` |
| source | VARCHAR | both / spotify / lastfm |
| platform | VARCHAR | `platform_family` |
| country | VARCHAR | after ZZ imputation; NULL = unknown |
| shuffle | BOOLEAN | |

Rows are sorted by year, artist, track, local_date, hour for compression.

## Parquet
`uv run python -m pipeline.export [--out PATH]` writes Zstd Parquet (stdout by default). It reads
`export_plays` from SITE_DB when set, else builds it in memory from the fixture.
`site/src/data/plays_explorer.parquet.sh` calls it, so a page that attaches
`data/plays_explorer.parquet` gets the file at build time.

## Done when
`uv run pytest tests/test_export_fixture.py` passes, `build_pipeline --fixtures` runs step 08, the full
suite, ruff and `cd site && npm run build` are green. Report the fixture Parquet size.
