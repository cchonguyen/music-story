# STATE (keep under 500 tokens; update at the end of every packet)

Wave: 1 (window 1 = W1, W2, W3 only)
Last gate: none yet. Gate 1 = W1+W2 on real data, >= 95% of 2023-26 scrobbles matched.

| Packet | Tier | Status |
|---|---|---|
| W0 schema, fixtures, golden tests | Opus | done (main) |
| W1 ingest `sql/01_ingest.sql` | Haiku | todo, spec `specs/W1_ingest.md` |
| W2 normalise + match | Opus | todo, spec `specs/W2_match.md` |
| W3 enrich clients | Sonnet | todo, spec `specs/W3_enrich.md` |
| W4 site + Access, W5 simple marts, W6 trap marts | | window 2 |
| W7 dims, W8 sessions, W9 taxonomy, W10 charts | | wave 2, after the fetch |

Next:
1. Lead spawns W1 (haiku-worker), W2 (opus-worker), W3 (sonnet-worker) in worktrees.
2. After merge, Charlie runs locally (outside Claude Code):
   `uv run python -m pipeline.build_pipeline --to 02` then
   `uv run python -m pipeline.enrich fetch` (hours; resumable).

Notes: fixture = ~47k plays, deterministic (seed 20260422). Spotify per-track fetch has no cap,
ordered by play count.
