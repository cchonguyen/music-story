# music-story: project implementation notes

As of 2026-10-27. `STATE.md` is still the place to resume work from, and `CLAUDE.md` holds the
working rules. This file collects the critical facts and decisions from both, plus the
enrichment and Spotify-quota work, so they can be reviewed in one place.

## 1. What it is

The project turns 19.5 years of listening history (Last.fm from Apr 2007, Spotify from Jul 2011,
both through Oct 2026) into a private story site. A DuckDB pipeline feeds an Observable Framework
site, which is served from Cloudflare Workers static assets at `music.charliechonguyen.com` behind
Cloudflare Access.

Privacy rules:
- Raw exports and databases never enter the repo or a prompt. Data is inspected only through
  counts, DESCRIBE or SUMMARIZE, and at most 10 sample rows from `dev_fixtures.duckdb`.
- Secrets live in `.env`, which is copied into worktrees by `.worktreeinclude`.
- The site is private. Access lets in one allowed account, `workers_dev` and `preview_urls` are
  off, and the Access app must exist before any deploy.

## 2. Data sources

| Source | Shape | Coverage |
| --- | --- | --- |
| Spotify Extended Streaming History (`Streaming_History_Audio_*.json`) | 130,513 rows, 35,646 track URIs. `ts` is when the track stopped (UTC), so start = `ts - ms_played` | Jul 2011 to 20 Oct 2026; ~25% of events are under 30 s |
| Spotify video history | tiny | ignored |
| Last.fm CSV (user brainchildvn) | 114,332 scrobbles: uts, artist, album, track and their MBIDs | Apr 2007 to 21 Oct 2026; 2007-2010 Last.fm only; 2014-2019 sparse |

Measured facts:
- A Last.fm scrobble time is about equal to the Spotify start time (median -0.6 s).
- There are 6,437 Last.fm double scrobbles within 60 s.
- 2022-2026 are near 1:1 duplicates across the two sources.
- 3,151 songs span several Spotify URIs (~33% of plays), so the canonical track id is the ISRC.
- Plays per URI have a long tail:

| Plays per URI | URIs | Share of plays | Share of listening time |
| --- | --- | --- | --- |
| all | 35,646 | 100% | 100% |
| 2 or more | 16,901 | 86% | 88% |
| 3 or more | 10,544 | 76% | 79% |
| 5 or more | 6,064 | 64% | 68% |
| 10 or more | 2,817 | 48% | 52% |

Timezone: Charlie always lived in Pacific time, so plays use America/Los_Angeles. A non-US
`conn_country` maps to its IANA zone through `data/country_tz.csv`; CA is guessed as
America/Vancouver.

## 3. Layout

| Path | Role |
| --- | --- |
| `sql/schema.sql` | The table contract. Changing it means updating `tests/test_schema.py` and STATE.md in the same commit |
| `sql/cache_schema.sql` | SQLite HTTP cache, fetch queue, pauses, request log and limits |
| `sql/NN_*.sql`, `sql/marts/` | SQL steps and analysis marts |
| `pipeline/` | Python steps, each exposing `run(con)`. `build_pipeline.py` runs them in order |
| `pipeline/normalize.py` | The only place normalisation lives |
| `pipeline/enrich*.py` | API clients, cache, queue seeding, parsing |
| `scripts/make_fixtures.py` | Seeded fixture (~47k plays, seed 20260422) written to `fixtures/raw/` and `dev_fixtures.duckdb` |
| `tests/` | Golden cases plus per-packet fixture acceptance tests |
| `site/` | Observable Framework site. Loaders call `pipeline/site_data.py`, which reads SITE_DB or else the fixture marts |
| `specs/Wn_*.md` | One spec per work packet |

## 4. Pipeline

`uv run python -m pipeline.build_pipeline [--fixtures] [--from NN] [--summary]`

| Step | Packet | What it does |
| --- | --- | --- |
| 00 | W0 | Apply `schema.sql` |
| 01 | W1 | Ingest raw exports into stg tables (`01_ingest.sql`) |
| 02 | W2 | Normalise, then match Last.fm to Spotify (passes 1-3 plus twin removal) to produce `events` |
| 03 | W3 | Parse the HTTP cache into `enr_*` tables (no network) |
| 04 | W7 | Dimensions: `track_uri_map`, `track_key_map`, `dim_track`, `dim_artist`, `dim_album`, `bridge_track_artist` |
| 05 | W8 | Sessions (20 min gap), country imputation, plays and skips |
| 06 | W9 | Genre map (222 rows) and `track_genre` |
| 07 | W5/W6 | Marts (`sql/marts/*.sql` in name order) |

Fetching from APIs is not a build step. It is a separate, resumable job:
`uv run python -m pipeline.enrich fetch`. It runs on Charlie's Mac, where the cache
(`~/.cache/music-story/http_cache.sqlite`), `.env` and the real DuckDB persist.

Gate 1 requires that at least 95% of 2023-26 scrobbles are matched. It passed at 95.81% after
matcher pass 3 and twin removal; the first run gave 89.57%.

## 5. Enrichment

### APIs and queue

| API | Endpoints | Pacing | Queued from |
| --- | --- | --- | --- |
| Spotify | `tracks`, `artists` | 1 req/s, plus a daily budget | Track URIs ranked by play count; artists cascade from track responses |
| MusicBrainz | `recording`, `search`, `isrc`, `artist` | 1.05 s | Last.fm MBIDs, Last.fm-only keys, the tail under the Spotify floor, and ISRCs from Spotify and Deezer |
| Last.fm | track, artist and album tags, `getInfo` | 0.25 s | Top 2,000 tracks, all artists, top 1,000 albums |
| Deezer | `track` (by ISRC), `search`, `id` | 0.11 s | Spotify ISRCs, Last.fm-only keys and the tail |

How the queue and cache work:
- Every response is cached, 404s included, so nothing is fetched twice.
- Storing a response, removing its queue row and queuing its follow-ups happen in one SQLite
  transaction, so killing the process never loses a step.
- Priority is the play-count rank, and follow-ups inherit their parent's rank.
- Failed items get one more round on the next `fetch`.

Cascades, as of 2026-10-23:
- `spotify.tracks` queues `spotify.artists`, `musicbrainz.isrc` and `deezer.track`.
- `deezer.search` keeps the first hit whose normalised artist and title equal the key, then
  queues `deezer.id`.
- `deezer.id` queues `musicbrainz.isrc`.
- `musicbrainz.isrc` and `musicbrainz.recording` queue `musicbrainz.artist`.

### Spotify dev-mode quota

Spotify confirmed in Jul 2026 that dev-mode quotas are one request count per developer account,
shared by every Client ID on it, so rotating Client IDs does not help. A quota 429 carries
`"reason": "QUOTA_EXCEEDED"`. The quota size is not published. Our first lockout came after about
600 requests at 3 req/s and lasted 24 h, until Fri 23 Oct 2026 14:44 PT. Pacing alone cannot
protect a count quota.

Defences, merged in PRs #1-#2:
- **Daily budget.** At most `--spotify-budget` (env `SPOTIFY_DAILY_BUDGET`, default 500) requests
  per rolling 24 h, counted in `request_log`. `0` turns the budget off and relies on the 429
  handling alone. Requests are logged either way.
- **429 handling.**
  - `QUOTA_EXCEEDED` pauses at once, for `Retry-After` or 24 h if it is missing.
  - A Spotify 429 without `Retry-After` pauses for 1 h.
  - Any `Retry-After` over 600 s pauses.
  - Every pause is stored in `api_pause` with its reason. The item stays queued, and reruns send
    nothing until the pause ends.
- **Play-count floor.** `--spotify-min-plays` (default 3) becomes an `api_limit` priority cap.
  Rows past it stay queued, so the floor can be moved later without a refetch.
- **Artists held.** The track payload already carries artist ids and names, and the artist call
  only adds genres, which Last.fm and MusicBrainz cover. `spotify.artists` therefore runs only with
  `--spotify-artists`, and then after every track.
- **Exit when paused.** `fetch` exits with the resume time when only paused APIs remain. `--wait`
  sits the pause out instead.

### What only Spotify provides

| Field | Used for | Non-Spotify fallback (after PR #3) |
| --- | --- | --- |
| ISRC | Canonical `track_id`, twin merging, the Deezer and MB-by-ISRC cascade | MB recording via scrobble MBID, then Deezer search match, then MB search (score 90 or more) |
| Album id, name, type and release date | `dim_album` | Album name carried by the plays (the export's Spotify album name), else Deezer's; keyed by primary artist and `album_norm` |
| Release date | `recording_year` / `work_year` | MusicBrainz first release date, then Deezer release date |
| `artists[]` credits | Featured artists in `bridge_track_artist` | None (primary artist only) |
| Duration | `dim_track.duration_ms` (first choice) | Local `trackdone` max, MB, Last.fm, Deezer |
| `explicit` | Unused | n/a |
| Artist genres | One of five genre inputs | Last.fm and MusicBrainz tags |

### Tail lookups (PR #3)

The tail is the Spotify-played `artist_norm::full_norm` keys whose most played URI is under the
floor, about 25k keys at the default of 3. They are queued for `musicbrainz.search` and
`deezer.search` behind the existing root items. `deezer.search` also covers Last.fm-only keys.
Matches land in `enr_deezer_match`. Rough cost: about 6 h of Deezer calls and 7 h of MusicBrainz
calls, with no daily cap on either.

### Daily runbook

```bash
git pull
uv run python -m pipeline.enrich fetch          # exits when only paused APIs remain
uv run python -m pipeline.enrich status         # done/queued/failed, floor, held rows, budget, pauses
# Options: --spotify-min-plays 5 | --spotify-budget 0 | --spotify-artists | --wait
```

When the fetch is done, run `build_pipeline` on the real data, then build the site with
`SITE_DB=build/music.duckdb` and deploy.

## 6. Site and deploy

- The site uses Observable Framework 1.13.4; the fixture build was 828 KB before the explorer. Pages
  are `index`, `artists`, `songs`, `genres`, `habits`, `places` and `explorer`.
- The explorer (`explorer.md`, W10b) queries every play and skip in the browser. Its data is one Zstd
  Parquet file from the `explorer_plays` view, written by `pipeline.site_data --parquet` and sorted by
  artist, album, title and time so repeated names compress: 612 KB for the fixture's 59k rows; size
  grows about linearly with rows. DuckDB-Wasm 1.29.0 comes from jsDelivr on that page only (about
  9 MB compressed on the first visit, then cached), and it fetches its parquet extension from
  extensions.duckdb.org. Only library code comes from those CDNs; the data stays behind Access.
  Search matches both the shown names and the pipeline's normalised names, so no normalisation rules
  are copied into JavaScript.
- To deploy, run `cd site && npm run build`, then `npx wrangler deploy` from the repo root.
  `wrangler.jsonc` is assets-only with a custom domain route.
- The fixture site went live on 2026-10-22 behind Access. Checks: `/`, `/index.html` and the data
  files return 302 to the Access login, and the workers.dev URL returns 404.

## 7. Decision log

| Date | Decision | Why |
| --- | --- | --- |
| 2026-10-22 | Host on Workers static assets, not Pages | Pages always serves a public `*.pages.dev` copy; Workers can switch every extra URL off |
| 2026-10-22 | Matcher pass 3 + twin removal | Gate 1 was 89.57%; after the change it is 95.81% |
| 2026-10-22 | Canonical track id = ISRC | 3,151 songs span several URIs |
| 2026-10-22 | Album key = `artist_norm::normalize_album(album_raw)` | Strips remaster noise; W7 and W9 must use it |
| 2026-10-22 | Normaliser drops only U+0300-036F and maps đ to d | Keeps Japanese dakuten and handles Vietnamese artists |
| 2026-10-22 | Spotify per-track lookups, cached | Feb 2026: dev mode lost batch endpoints and popularity |
| 2026-10-22 | Spotify at 1 req/s | 3 req/s drew a 24 h lockout after ~600 requests |
| 2026-10-23 | Daily Spotify budget of 500 as a probe; pause on QUOTA_EXCEEDED | The quota is a per-account count, so pacing does not protect it |
| 2026-10-23 | Spotify floor of 3+ plays (`--spotify-min-plays 5` also available) | 10,544 URIs cover 76% of plays |
| 2026-10-23 | `spotify.artists` held by default | Genres only, already covered by Last.fm and MB |
| 2026-10-23 | Tail ISRCs from Deezer and MB search; `dim_album` fallback from play album names | ISRCs and albums no longer depend on the Spotify quota |
| 2026-10-27 | Explorer loads DuckDB-Wasm from jsDelivr, not Framework's self-hosted DuckDBClient | Self-hosting puts `duckdb-eh.wasm` (34 MiB) and `duckdb-mvp.wasm` (39 MiB) in `dist/`, over the 25 MiB per-file limit of Workers static assets. Rejected: Arrow IPC with a plain-JS explorer (7 MB uncompressed vs 0.6 MB Parquet on the fixture, and no SQL) |
| 2026-10-27 | Explorer rows include skips, flagged `is_skip` | Skip rate per artist or track needs them; counts and hours leave them out so they match the marts |

## 8. Open items

- Run the first budgeted Spotify fetch after the unlock. Use `status` to learn the real quota and
  tune `--spotify-budget`.
- Review the genre map parents with Charlie: blues to jazz, hardcore to metal, reggae/dub/ska to
  world.
- Platform `ios` is matched exactly, but 4,104 of 12,036 real `other` plays are iOS, iPhone or
  iPad strings. The proposed W1 fix is a case-insensitive match plus a fixture update.
- When the fetch is done: real `build_pipeline`, then the site build with SITE_DB, then deploy.
- The explorer has only been checked on the fixture, in a headless browser with the CDN files served
  locally (this cloud container blocks jsDelivr and extensions.duckdb.org). Check it once on the
  deployed site.
- Remaining packets: W11 stats (real data), W12 export, W13 story.
