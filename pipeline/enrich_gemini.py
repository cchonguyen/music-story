"""Gemini LLM artist genre enrichment client and runner.

Batches artists with >= 3 plays that are unclassified or stuck on umbrella self-tags,
passes local evidence (titles, raw Last.fm tags, MusicBrainz genres, country), and
writes structured outputs into http_cache.sqlite under:
  api="gemini", endpoint="artist_genre:{model_id}:{prompt_version}"
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import duckdb
import httpx

from pipeline import config
from pipeline.enrich_cache import Cache

DEFAULT_MODEL = os.environ.get("GENRE_LLM_MODEL", "gemini-3.6-flash")
PROMPT_VERSION = "v1"
BATCH_SIZE = 25


def load_api_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    env_file = config.REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


def get_candidate_artists(con: duckdb.DuckDBPyConnection, min_plays: int = 3) -> list[str]:
    """Find artists with >= min_plays that are unclassified or lack a specific sub-style."""
    rows = con.execute("""
        WITH p AS (SELECT artist_id, count(*) AS n FROM plays GROUP BY 1),
        art_genres AS (
            SELECT primary_artist_id AS artist_id,
                   count(DISTINCT tg.style) AS style_count,
                   count(DISTINCT tg.style) FILTER (WHERE tg.style <> tg.parent_genre) AS substyle_count
            FROM dim_track dt
            JOIN track_genre tg USING (track_id)
            GROUP BY 1
        )
        SELECT a.artist_norm
        FROM dim_artist a
        JOIN p USING (artist_id)
        LEFT JOIN art_genres ag USING (artist_id)
        WHERE p.n >= ? AND (ag.style_count IS NULL OR ag.substyle_count = 0)
        ORDER BY p.n DESC
    """, [min_plays]).fetchall()
    return [r[0] for r in rows]


def build_evidence(con: duckdb.DuckDBPyConnection, artist_norm: str) -> dict[str, Any] | None:
    row = con.execute("SELECT artist_norm, name, country FROM dim_artist WHERE artist_norm = ?", [artist_norm]).fetchone()
    if not row:
        return None
    a_norm, disp_name, country = row
    tracks = [r[0] for r in con.execute("""
        SELECT t.title FROM dim_track t JOIN dim_artist a ON a.artist_id = t.primary_artist_id
        WHERE a.artist_norm = ? LIMIT 4
    """, [a_norm]).fetchall()]
    tags = [r[0] for r in con.execute("""
        SELECT l.tag FROM enr_lastfm_tags l WHERE l.entity_key = ? AND l.entity_type = 'artist' LIMIT 6
    """, [a_norm]).fetchall()]
    mb_genres = [r[0] for r in con.execute("""
        SELECT unnest(genres) FROM enr_mb_artist m JOIN dim_artist a USING (artist_mbid)
        WHERE a.artist_norm = ?
    """, [a_norm]).fetchall()][:6]
    return {
        "artist_norm": a_norm,
        "name": disp_name,
        "country": country or "unknown",
        "sample_tracks": tracks,
        "lastfm_tags": tags,
        "mb_genres": mb_genres,
    }


def call_gemini_batch(api_key: str, model_id: str, valid_styles: list[str], batch: list[dict]) -> list[dict]:
    prompt = f"""
You are an expert music genre taxonomist. For each artist below, select 1 to 3 styles strictly from this allowed parent -> style list:
{json.dumps(valid_styles)}

Rules:
1. Prefer specific sub-styles over broad umbrella self-tags whenever there is evidence.
2. If evidence is ambiguous, assign lower weight or confidence.
3. Return strict JSON array matching the artist list.

Allowed parent genres are ONLY: electronic, pop, rock, hip hop, r&b, country, soundtrack, classical, jazz, world.

Artists to classify:
{json.dumps(batch, indent=2)}

Output format:
{{
  "results": [
    {{
      "artist_norm": "...",
      "styles": [
        {{"parent": "...", "style": "...", "weight": 0.0 to 1.0, "confidence": "high|medium|low"}}
      ],
      "reasoning": "brief 1 sentence"
    }}
  ]
}}
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
    resp = httpx.post(
        url,
        json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}},
        timeout=60.0,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini API returned status {resp.status_code}: {resp.text}")
    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(text)
    return parsed.get("results", [])


def run_enrichment(
    con: duckdb.DuckDBPyConnection,
    cache: Cache,
    model_id: str = DEFAULT_MODEL,
    prompt_version: str = PROMPT_VERSION,
    min_plays: int = 3,
    limit: int | None = None,
) -> int:
    api_key = load_api_key()
    if not api_key:
        print("GEMINI_API_KEY not set in environment or .env, skipping Gemini enrichment.", file=sys.stderr)
        return 1

    endpoint = f"artist_genre:{model_id}:{prompt_version}"
    all_candidates = get_candidate_artists(con, min_plays=min_plays)

    # Check cache to see who is already done
    needed = []
    for c in all_candidates:
        if cache.get("gemini", endpoint, c) is None:
            needed.append(c)

    if limit is not None:
        needed = needed[:limit]

    print(f"Gemini enrichment: {len(needed)} artists to fetch (of {len(all_candidates)} candidates with >={min_plays} plays)")
    if not needed:
        return 0

    valid_styles = [
        f"{r[1]} -> {r[0]}"
        for r in con.execute(
            "SELECT DISTINCT style, parent_genre FROM genre_map WHERE is_genre ORDER BY parent_genre, style"
        ).fetchall()
    ]

    batches = [needed[i : i + BATCH_SIZE] for i in range(0, len(needed), BATCH_SIZE)]
    total_classified = 0

    for idx, batch_keys in enumerate(batches, 1):
        batch_evidence = []
        for k in batch_keys:
            ev = build_evidence(con, k)
            if ev:
                batch_evidence.append(ev)

        if not batch_evidence:
            continue

        print(f"  Batch {idx}/{len(batches)} ({len(batch_evidence)} artists)...", flush=True)
        try:
            results = call_gemini_batch(api_key, model_id, valid_styles, batch_evidence)
            for res in results:
                a_norm = res.get("artist_norm")
                if a_norm:
                    body = json.dumps(res, ensure_ascii=False)
                    cache.put("gemini", endpoint, a_norm, 200, body, [])
                    total_classified += 1
            time.sleep(1.0)  # Gentle pacing between batches
        except Exception as e:  # noqa: BLE001
            print(f"  Error in batch {idx}: {e}", file=sys.stderr)

    print(f"Gemini enrichment complete: {total_classified} artist profiles cached.")
    return 0


def main() -> None:
    con = duckdb.connect(str(config.MUSIC_DB), read_only=True)
    cache_path = config.CACHE_DIR / "http_cache.sqlite"
    cache = Cache(cache_path)
    try:
        run_enrichment(con, cache)
    finally:
        cache.close()
        con.close()


if __name__ == "__main__":
    main()
