# music-story
A serverless, local-first analytics engine and interactive story exploring 19.5 years of personal listening telemetry using DuckDB, Python, and DuckDB-Wasm.

## Setup (macOS)
```sh
brew install uv            # once
uv sync                    # Python 3.12 + dependencies into .venv
cp .env.example .env       # then fill DATA_DIR and API keys
uv run python scripts/make_fixtures.py
uv run pytest
```

## Run
```sh
uv run python -m pipeline.build_pipeline --fixtures   # whole pipeline on synthetic data
uv run python -m pipeline.build_pipeline              # real data -> build/music.duckdb
uv run python -m pipeline.enrich fetch                # long API fetch, resumable
```

The raw exports, every database and the API cache stay on your machine. Only code and the
sanitised site data are committed. See `CLAUDE.md` for working rules and `STATE.md` for progress.
