"""Paths and settings. Everything resolves from the repo root of the current
checkout, so each git worktree gets its own fixtures and build outputs.
Only CACHE_DIR is shared, so API responses are fetched once per machine."""

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

SQL_DIR = REPO_ROOT / "sql"
SCHEMA_SQL = SQL_DIR / "schema.sql"
CACHE_SCHEMA_SQL = SQL_DIR / "cache_schema.sql"
COUNTRY_TZ_CSV = REPO_ROOT / "data" / "country_tz.csv"

FIXTURE_DB = REPO_ROOT / "dev_fixtures.duckdb"
FIXTURE_RAW_DIR = REPO_ROOT / "fixtures" / "raw"


def _path(name: str, default: Path | None) -> Path | None:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


# Folder holding the real Streaming_History_*.json files and the Last.fm CSV.
DATA_DIR = _path("DATA_DIR", None)
# The real pipeline database. Never committed.
MUSIC_DB = _path("MUSIC_DB", REPO_ROOT / "build" / "music.duckdb")
# HTTP response cache for 03_enrich.py, outside the repo on purpose.
CACHE_DIR = _path("CACHE_DIR", Path.home() / ".cache" / "music-story")

LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY")
LASTFM_USER = os.environ.get("LASTFM_USER")
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
MUSICBRAINZ_CONTACT = os.environ.get("MUSICBRAINZ_CONTACT")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
