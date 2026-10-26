# Project Overview (Owner's Manual)

## What This App Does
- Turns 19.5 years of Spotify + Last.fm listening history into a private story site at
  music.charliechonguyen.com (behind Cloudflare Access). Detail: `docs/PROJECT.md`.

## Active External Services & Keys
- Cloudflare (Workers static assets + Access), Spotify, Last.fm, Deezer, MusicBrainz.
  Key names live in `.env.example`; values only in `.env`.

## Current Build Status
- **Live & Verified:** Fixture site behind Access; packets W0-W10 merged (see `STATE.md`).
- **In Progress:** Daily enrichment fetch (Spotify quota-limited).
- **Up Next:** Per `STATE.md` "Next".
