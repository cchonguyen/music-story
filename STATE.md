# STATE (keep under 500 tokens; update at the end of every packet)

Wave: 1 (window 1 done, merged 2026-10-22). Waiting on Charlie's real-data run + fetch.
Last gate: none yet. Gate 1 = W1+W2 on real data, >= 95% of 2023-26 scrobbles matched
(fixture: 98.18%).

| Packet | Tier | Status |
|---|---|---|
| W0 schema, fixtures, golden tests | Opus | done (main) |
| W1 ingest `sql/01_ingest.sql` | Haiku | done (main), first try |
| W2 normalise + match | Opus | done (main), first try |
| W3 enrich clients | Sonnet | done (main), first try + lead fix (album key) |
| W4 site + Access, W5 simple marts, W6 trap marts | | window 2 |
| W7 dims, W8 sessions, W9 taxonomy, W10 charts | | wave 2, after the fetch |

Next:
1. Charlie runs locally (outside Claude Code):
   `uv run python -m pipeline.build_pipeline --to 02` -> paste only the `match:` line (Gate 1).
   `uv run python -m pipeline.enrich status` -> paste the hours estimate.
   `uv run python -m pipeline.enrich fetch` (hours; resumable, Ctrl+C safe).
2. Lead: if Gate 1 >= 95%, start window 2 (W4, W5, W6).

Decisions (window 1 review):
- Album key = `artist_norm::normalize_album(album_raw)` (`normalize_album` in normalize.py:
  remaster noise off + text rules). W7/W9 must use it for album_norm.
- enr_local_duration reads stg_spotify; NULL `skipped` counts as not skipped (old exports).
- Follow-up fetch items (Spotify artists, ISRC, Deezer) inherit their track's rank.
- Retry-After > 600 s pauses that api for the run; failed items retry once on next `fetch`.
- Open: platform `ios` is exact match; older `iOS 12.x (...)` strings land in `other`.
  Check the count after the real run before changing the rule.

Notes: fixture = ~47k plays, deterministic (seed 20260422). Spotify per-track fetch has no cap,
ordered by play count.
