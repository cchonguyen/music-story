# music-story

music-story is a local-first analytics engine and static story site built from a personal listening history. It uses DuckDB and Python to build the data, and Observable Framework to render the story site.

## Status and license

This is a personal project. All rights reserved; see `LICENSE`. No personal data is included in this repository.

## What is not in this repo

This repository does not contain:

- The raw Spotify and Last.fm exports.
- The databases.
- The API cache.
- API keys.
- The deployed site's data.

The deployed site is behind an access-control gate. It is not published.

## Run with synthetic data

Synthetic data needs no keys and no exports. Run these commands from the repository root:

```bash
brew install uv                                       # macOS; see the uv docs for other systems
uv sync                                               # install Python 3.12 and the dependencies into .venv
cp .env.example .env                                  # leave the values blank; fixtures need no keys
uv run python scripts/make_fixtures.py                # generate the synthetic listening data
uv run pytest                                         # run the Python tests
uv run ruff check                                     # lint the Python code
uv run python -m pipeline.build_pipeline --fixtures   # run the whole pipeline on synthetic data
```

## Build the site

Node 18 or later is required. Run the lint step from the repository root, then build the site:

```bash
npm run lint                  # check the JavaScript config files
cd site && npm ci && npm run build   # install site dependencies and build; output is written to site/dist
```

## Real data and API keys

Real runs need your own exports. Place them where you like, then set `DATA_DIR` in `.env` to point at them.

API keys go in `.env`. These cover Last.fm, Spotify, a MusicBrainz contact address, and Gemini. `.env.example` lists the variable names. Do not commit `.env`.

Enrichment is resumable and rate-limited, so an interrupted run can be restarted without losing finished work.

## Deployment

The site is deployed as Cloudflare Workers static assets, configured in `wrangler.jsonc`. The route in that file is a placeholder for your own domain. Enable Cloudflare Access before any deploy.

## Project docs

- `CLAUDE.md`: working rules for contributors and coding agents.
- `STATE.md`: current progress.
- `docs/PROJECT.md`: decision log.
- `docs/CLOUD_SETUP.md`: optional \$0 cloud automation with Cloudflare R2 and GitHub Actions.
