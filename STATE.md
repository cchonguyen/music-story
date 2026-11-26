# STATE (keep under 500 tokens; update at the end of every packet)

Wave: 2 merged. Real build + deploy verified behind Cloudflare Access.

| Packet | Tier | Status |
|---|---|---|
| W0–W10 core pipeline & story site | Mixed | done (main) |
| Artist export `pipeline/artist_genre.py` | Opus | done (`build/artist_genres.json`, legacy `MIN_SHARE=0.15`) |
| W9b umbrella disaggregation | Opus | done (ramp `[0.10,0.30]` + two-stage soft-hinge `[0.10,0.20]`) |
| W9c genre xray, hierarchy & clock marts | Sonnet | done (`mart_genre_xray`, `mart_genre_hierarchy`, `mart_genre_clock`) |
| W10c–W10d genres & explorer upgrades | Sonnet | done (DuckDB-Wasm `LEFT JOIN xray`, multi-facet filters, tables) |
| W9d–W9g 10-parent + Gemini + Discogs + vendor weights | Antigravity | done (main; 10 parents, 357-row `genre_map.csv`, 7,932 artists, 99.83% coverage) |
| W14 artist genre sheet (`pipeline/artist_sheet.py`) | Opus | done (main; export/import + browser CSV button on `artists.md`) |
| W15 track genre sheet (`pipeline/track_sheet.py`) | Opus | slice 1 done (`06b` step, `track_genre_override`, browser button on `songs.md`) |
| Audit cleanup (`antigravity/audit-cleanup`) | Antigravity | in progress (bug fixes, sheet consolidation, Parquet xray, doc/privacy scrub) |

Next:
1. Enrichment fetch (`uv run python -m pipeline.enrich fetch`) is resumable via `scripts/nightly_enrich.sh` (`--spotify-cover 0.80` default; `--spotify-min-plays N` overrides).
2. Real-data site deploy: `SITE_DB=build/music.duckdb cd site && npm run build`, then `npx wrangler deploy` (configure your domain in `wrangler.jsonc` and enable Cloudflare Access first).

Decisions (key):
- Album key = `artist_norm::normalize_album(album_raw)`.
- `enr_local_duration` reads `stg_spotify`; NULL `skipped` counts as not skipped.
- Schema includes `artist_genre_override` and `track_genre_override` (step `06b`).
- Open: genre map parents to review (`blues -> jazz`, `reggae/dub/ska -> world`).
- Open: decide whether marts should also drop incognito plays (currently only `explorer_plays` and `mart_genre_xray` drop them).

Notes: fixture = ~47k plays, deterministic (seed 20260422).
