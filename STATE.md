# STATE (keep under 500 tokens; update at the end of every packet)

Wave: 1 done (windows 1+2, 2026-10-22). Fetch running on Charlie's machine.
Last gate: Gate 1 PASSED 95.81% (2026-10-22, after W2 rev 2; first run 89.57%).

| Packet | Tier | Status |
|---|---|---|
| W0 schema, fixtures, golden tests | Opus | done (main) |
| W1 ingest `sql/01_ingest.sql` | Haiku | done (main), first try |
| W2 normalise + match | Opus | done (main); lead rev 2: pass 3 + twins after Gate 1 miss |
| W3 enrich clients | Sonnet | done (main), first try + lead fix (album key) |
| W4 site + deploy config | Sonnet | done (main), first try; Framework 1.13.4, 828 KB build |
| W5 simple marts | Haiku | done (main), first try |
| W6 trap marts | Opus | done (main), first try |
| W7 dims `pipeline/dims.py` | Opus | done (main); lead fixed fixture (no 404 on scenario tracks) |
| W8 sessions `sql/05_sessions.sql` | Sonnet | done (main); lead fixed test (listen_ms sum) |
| W9 genre `pipeline/genre.py` + csv | Sonnet | done (main); lead fix (MB genre join), 222-row map |
| W10 chapters + charts | Sonnet | done (main), first try; site_data trims top-N marts |

Next:
1. Fetch 2026-10-23: Last.fm done. Spotify locked out after ~600 req (until Fri 23 Oct 14:44 PT).
   Dev-mode quota is a per-account request count, so fetch now caps Spotify at SPOTIFY_DAILY_BUDGET
   (500/rolling 24 h), pauses on QUOTA_EXCEEDED, and only takes tracks with 5+ plays (6,064 URIs,
   64% of plays; `--spotify-min-plays`). Deezer + MB isrc only get work from Spotify ISRCs. fetch
   exits when only paused apis remain (`--wait` sits it out). Charlie reruns `fetch` daily.
2. Fixture site LIVE 2026-10-22 behind Access (team REDACTED-ACCESS-TEAM, allow redacted-email@example.com).
   Verified: /, /index.html, /_file/data/year.json all 302 to Access login; workers.dev 404.
   Real-data deploy: build with SITE_DB=build/music.duckdb (fixture otherwise).
3. Wave 2 merged. `build_pipeline --fixtures` runs 00-07 end to end (fixture enr_* copied, never the real
   cache). Next: when the fetch is done, `build_pipeline` (real), then site build with SITE_DB + deploy.

Decisions (window 1 review):
- Gate 1 fix (pass 3 + twins): see CLAUDE.md decision log and specs/W2_match.md rule 3.
- Album key = `artist_norm::normalize_album(album_raw)` (`normalize_album` in normalize.py:
  remaster noise off + text rules). W7/W9 must use it for album_norm.
- enr_local_duration reads stg_spotify; NULL `skipped` counts as not skipped (old exports).
- Follow-up fetch items (Spotify artists, ISRC, Deezer) inherit their track's rank.
- Pauses (Retry-After > 600 s, QUOTA_EXCEEDED, budget) live in api_pause; failed items retry once on next `fetch`.
- Open: PR 2 = MB search for Spotify tracks under the floor + dim_album fallback key (needs lead).
- Open: genre map parents to review with Charlie (blues->jazz, hardcore->metal, reggae/dub/ska->world).
- Open: platform `ios` is exact match; 4,104 of 12,036 real `other` plays are iOS/iPhone/iPad
  strings. Proposed W1 fix (case-insensitive ios/iphone/ipad -> ios + fixture update) before W8.

Notes: fixture = ~47k plays, deterministic (seed 20260422). Spotify per-track fetch ordered by play
count, artists after all tracks.
