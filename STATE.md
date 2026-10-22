# STATE (keep under 500 tokens; update at the end of every packet)

Wave: 1 (window 1 done 2026-10-22). Fetch running on Charlie's machine.
Last gate: Gate 1 PASSED 95.81% (2026-10-22, after W2 rev 2; first run 89.57%).
Real: pass1 58159, pass2 450, pass3 2021, twins 1143; events both 60630 / spotify 69766 / lastfm 46120.

| Packet | Tier | Status |
|---|---|---|
| W0 schema, fixtures, golden tests | Opus | done (main) |
| W1 ingest `sql/01_ingest.sql` | Haiku | done (main), first try |
| W2 normalise + match | Opus | done (main); lead rev 2: pass 3 + twins after Gate 1 miss |
| W3 enrich clients | Sonnet | done (main), first try + lead fix (album key) |
| W4 site + deploy config | Sonnet | in progress, spec `specs/W4_site.md` |
| W5 simple marts | Haiku | done (main), first try |
| W6 trap marts | Opus | done (main), first try |
| W7 dims, W8 sessions, W9 taxonomy, W10 charts | | wave 2, after the fetch |

Next:
1. Charlie: `uv run python -m pipeline.enrich status` (hours), then `uv run python -m pipeline.enrich fetch`.
2. Lead: merge W4. Then Charlie creates the Access app (steps from lead), lead deploys.

Decisions (window 1 review):
- Gate 1 miss causes (real 2023-26, 2,660 unmatched): 986 double scrobbles 2-4 min apart;
  ~700 same song on Spotify 3-60 min off (all platforms; real pass 3: median 15 min,
  95% scrobble before play); ~1,100 other song playing (other app/device,
  genuinely Last.fm-only). Fix: pass 3 (equal names, full listen, <= 1 h) then twins (<= 360 s,
  same full_norm -> lfm_self_dupes). Pass 3 is 337/339 correct vs fixture truth_links.
  Fixture precision now scored against truth_links (fx.match_links only holds pass 1/2 pairs).
- Album key = `artist_norm::normalize_album(album_raw)` (`normalize_album` in normalize.py:
  remaster noise off + text rules). W7/W9 must use it for album_norm.
- enr_local_duration reads stg_spotify; NULL `skipped` counts as not skipped (old exports).
- Follow-up fetch items (Spotify artists, ISRC, Deezer) inherit their track's rank.
- Retry-After > 600 s pauses that api for the run; failed items retry once on next `fetch`.
- Open: platform `ios` is exact match; 4,104 of 12,036 real `other` plays are iOS/iPhone/iPad
  strings. Proposed W1 fix (case-insensitive ios/iphone/ipad -> ios + fixture update) before W8.

Notes: fixture = ~47k plays, deterministic (seed 20260422). Spotify per-track fetch has no cap,
ordered by play count.
