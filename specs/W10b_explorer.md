# W10b: explorer page

Tier: lead (Opus). Built 2026-10-27 on the fixture. Never deploy.

## What
- `sql/marts/40_explorer.sql`: view `explorer_plays`, one row per play or skip (`is_skip`) with names
  (artist, title, album), normalised names (`artist_norm`, `title_norm`), the track's heaviest
  parent_genre/style, minutes (`ms_imputed`), platform, country, source. A view, so no mart loader.
- `pipeline/site_data.py --parquet explorer_plays`: Zstd Parquet on stdout, sorted by artist, album,
  title, ts. Loader `site/src/data/plays_explorer.parquet.sh`.
- `site/src/explorer.md`: DuckDB-Wasm 1.29.0 imported from jsDelivr (not Framework's DuckDBClient),
  search over shown and normalised names, year range, parent genre, group by
  track/artist/album/style/year/platform/country; plays per month chart and a grouped table.

## Why not DuckDBClient
Framework self-hosts `duckdb-eh.wasm` (34 MiB) and `duckdb-mvp.wasm` (39 MiB). Workers static assets
cap one file at 25 MiB, so `wrangler deploy` would fail. The CDN import keeps them out of `dist/`.
DuckDB-Wasm 1.29 also loads its parquet extension at run time from extensions.duckdb.org.

## Done when
`uv run pytest` and `uv run ruff check` green, `cd site && npm run build` succeeds, the page works in a
browser on the fixture.
