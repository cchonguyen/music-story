# STATE (keep under 500 tokens; update at the end of every packet)

Wave: 1 (window 1 done, merged 2026-10-22). Waiting on Charlie's real-data run + fetch.
Last gate: Gate 1 FAILED on real data, 89.57% (2026-10-22). Fix merged: pass 3 + twins (W2 rev).
Gate 1 = W1+W2 on real data, >= 95% of 2023-26 scrobbles matched. Expected after fix ~96%.

| Packet | Tier | Status |
|---|---|---|
| W0 schema, fixtures, golden tests | Opus | done (main) |
| W1 ingest `sql/01_ingest.sql` | Haiku | done (main), first try |
| W2 normalise + match | Opus | done (main); lead rev 2: pass 3 + twins after Gate 1 miss |
| W3 enrich clients | Sonnet | done (main), first try + lead fix (album key) |
| W4 site + Access, W5 simple marts, W6 trap marts | | window 2 |
| W7 dims, W8 sessions, W9 taxonomy, W10 charts | | wave 2, after the fetch |

Next:
1. Charlie reruns `uv run python -m pipeline.build_pipeline --to 02`, pastes the `match:` line.
   Spotify fetch may already run (`enrich fetch --api spotify`, unaffected by matching).
   Then `enrich status` (hours estimate) and `enrich fetch` for the rest.
2. Lead: if Gate 1 >= 95%, start window 2 (W4, W5, W6).

Decisions (window 1 review):
- Gate 1 miss causes (real 2023-26, 2,660 unmatched): 986 double scrobbles 2-4 min apart;
  ~700 same song on Spotify 3-60 min off (iPhone); ~1,100 other song playing (other app/device,
  genuinely Last.fm-only). Fix: pass 3 (equal names, full listen, <= 1 h) then twins (<= 360 s,
  same full_norm -> lfm_self_dupes). Pass 3 is 337/339 correct vs fixture truth_links.
  Fixture precision now scored against truth_links (fx.match_links only holds pass 1/2 pairs).
- Album key = `artist_norm::normalize_album(album_raw)` (`normalize_album` in normalize.py:
  remaster noise off + text rules). W7/W9 must use it for album_norm.
- enr_local_duration reads stg_spotify; NULL `skipped` counts as not skipped (old exports).
- Follow-up fetch items (Spotify artists, ISRC, Deezer) inherit their track's rank.
- Retry-After > 600 s pauses that api for the run; failed items retry once on next `fetch`.
- Open: platform `ios` is exact match; older `iOS 12.x (...)` strings land in `other`.
  Check the count after the real run before changing the rule.

Notes: fixture = ~47k plays, deterministic (seed 20260422). Spotify per-track fetch has no cap,
ordered by play count.
