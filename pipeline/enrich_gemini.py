"""Gemini LLM artist genre enrichment client and runner.

Batches artists with >= 3 plays that are unclassified or stuck on umbrella self-tags,
passes local evidence (titles, raw Last.fm tags, MusicBrainz genres, country), and
writes structured outputs into http_cache.sqlite under:
  api="gemini", endpoint="artist_genre:{model_id}:{prompt_version}"
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any

import duckdb
import httpx

from pipeline import config
from pipeline.enrich_cache import Cache

logger = logging.getLogger(__name__)

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


def get_candidate_artists(
    con: duckdb.DuckDBPyConnection,
    min_plays: int = 1,
    scope: str = "all",
) -> list[str]:
    """Find candidate artists ordered descending by total plays.

    - scope='all': returns all catalog artists with >= min_plays.
    - scope='gaps': returns artists with >= min_plays that lack a specific sub-style.
    """
    if scope == "all":
        rows = con.execute("""
            WITH p AS (
                SELECT t.primary_artist_id AS artist_id, count(*) AS n
                FROM plays p JOIN dim_track t USING (track_id)
                GROUP BY 1
            )
            SELECT a.artist_norm
            FROM dim_artist a
            LEFT JOIN p USING (artist_id)
            WHERE coalesce(p.n, 0) >= ?
            ORDER BY coalesce(p.n, 0) DESC, a.artist_norm ASC
        """, [min_plays]).fetchall()
        return [r[0] for r in rows]

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


def build_evidence_lookup(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, Any]]:
    """Vectorized prefetch of metadata and ground-truth tags for all artists in < 0.2s."""
    meta = dict(con.execute("SELECT artist_norm, (name, country) FROM dim_artist").fetchall())

    tracks: dict[str, list[str]] = {}
    for a_norm, title in con.execute("""
        SELECT a.artist_norm, t.title
        FROM dim_track t
        JOIN dim_artist a ON a.artist_id = t.primary_artist_id
        QUALIFY row_number() OVER (PARTITION BY a.artist_norm ORDER BY t.track_id) <= 4
    """).fetchall():
        tracks.setdefault(a_norm, []).append(title)

    tags: dict[str, list[str]] = {}
    for a_norm, tag in con.execute("""
        SELECT entity_key, tag
        FROM enr_lastfm_tags
        WHERE entity_type = 'artist'
        QUALIFY row_number() OVER (PARTITION BY entity_key ORDER BY count DESC) <= 6
    """).fetchall():
        tags.setdefault(a_norm, []).append(tag)

    mb_genres: dict[str, list[str]] = {}
    for a_norm, g in con.execute("""
        SELECT a.artist_norm, lower(trim(unnest(m.genres)))
        FROM enr_mb_artist m
        JOIN dim_artist a USING (artist_mbid)
        WHERE len(m.genres) > 0
    """).fetchall():
        if len(mb_genres.get(a_norm, [])) < 6:
            mb_genres.setdefault(a_norm, []).append(g)

    discogs_styles: dict[str, list[str]] = {}
    for a_norm, s in con.execute("""
        SELECT artist_norm, lower(trim(unnest(styles)))
        FROM enr_discogs_artist
        WHERE len(styles) > 0
    """).fetchall():
        if len(discogs_styles.get(a_norm, [])) < 6:
            discogs_styles.setdefault(a_norm, []).append(s)

    lookup = {}
    for a_norm, (name, country) in meta.items():
        lookup[a_norm] = {
            "artist_norm": a_norm,
            "name": name,
            "country": country or "unknown",
            "sample_tracks": tracks.get(a_norm, []),
            "lastfm_tags": tags.get(a_norm, []),
            "mb_genres": mb_genres.get(a_norm, []),
            "discogs_styles": discogs_styles.get(a_norm, []),
        }
    return lookup


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
    discogs_styles = [r[0] for r in con.execute("""
        SELECT unnest(styles) FROM enr_discogs_artist WHERE artist_norm = ?
    """, [a_norm]).fetchall()][:6]
    return {
        "artist_norm": a_norm,
        "name": disp_name,
        "country": country or "unknown",
        "sample_tracks": tracks,
        "lastfm_tags": tags,
        "mb_genres": mb_genres,
        "discogs_styles": discogs_styles,
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

    for attempt in range(1, 4):
        try:
            resp = httpx.post(
                url,
                json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}},
                timeout=60.0,
            )
            if resp.status_code == 429:
                wait_sec = 4.0 * attempt
                print(f"    [Rate-limit 429] Pacing {wait_sec:.1f}s before retry...", flush=True)
                time.sleep(wait_sec)
                continue
            if resp.status_code != 200:
                raise RuntimeError(f"Gemini API returned status {resp.status_code}: {resp.text}")
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
            return parsed.get("results", [])
        except httpx.RequestError:
            if attempt == 3:
                raise
            time.sleep(2.0 * attempt)
    return []


def load_valid_styles() -> list[str]:
    """Load canonical parent -> style list directly from data/genre_map.csv."""
    import csv
    styles = set()
    with open(config.REPO_ROOT / "data" / "genre_map.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("is_genre", "").lower() == "true":
                pg = row.get("parent_genre", "").strip().lower()
                st = row.get("style", "").strip().lower()
                if pg and st:
                    styles.add(f"{pg} -> {st}")
    return sorted(styles)


def run_enrichment(
    candidates: list[str],
    evidence_lookup: dict[str, dict[str, Any]],
    cache: Cache,
    model_id: str = DEFAULT_MODEL,
    prompt_version: str = PROMPT_VERSION,
    limit: int | None = None,
    workers: int = 4,
) -> int:
    import concurrent.futures

    api_key = load_api_key()
    if not api_key:
        print("GEMINI_API_KEY not set in environment or .env, skipping Gemini enrichment.", file=sys.stderr)
        return 1

    endpoint = f"artist_genre:{model_id}:{prompt_version}"

    # Check cache to see who is already done
    needed = []
    for c in candidates:
        if cache.get("gemini", endpoint, c) is None:
            needed.append(c)

    if limit is not None:
        needed = needed[:limit]

    print(f"Gemini enrichment: {len(needed)} artists to fetch (of {len(candidates)} candidate artists)")
    if not needed:
        return 0

    valid_styles = load_valid_styles()
    print(f"Loaded {len(valid_styles)} canonical styles from genre_map.csv.")

    batches = [needed[i : i + BATCH_SIZE] for i in range(0, len(needed), BATCH_SIZE)]
    total_batches = len(batches)
    total_classified = 0
    start_time = time.time()
    completed_batches = 0

    def process_batch(idx_and_keys: tuple[int, list[str]]) -> int:
        idx, batch_keys = idx_and_keys
        batch_evidence = [evidence_lookup[k] for k in batch_keys if k in evidence_lookup]
        if not batch_evidence:
            return 0
        classified = 0
        try:
            results = call_gemini_batch(api_key, model_id, valid_styles, batch_evidence)
            for res in results:
                a_norm = res.get("artist_norm")
                if a_norm:
                    body = json.dumps(res, ensure_ascii=False)
                    cache.put("gemini", endpoint, a_norm, 200, body, [])
                    classified += 1
            time.sleep(0.2)
        except Exception as e:  # noqa: BLE001
            print(f"  Error in batch {idx}: {e}", file=sys.stderr)
        return classified

    print(f"Processing {total_batches} batches with {workers} parallel workers...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        batch_inputs = list(enumerate(batches, 1))
        futures = {executor.submit(process_batch, item): item[0] for item in batch_inputs}
        for future in concurrent.futures.as_completed(futures):
            b_idx = futures[future]
            try:
                classified_count = future.result()
                total_classified += classified_count
            except Exception as e:  # noqa: BLE001
                print(f"  Batch {b_idx} generated exception: {e}", file=sys.stderr)
            completed_batches += 1
            if completed_batches % 10 == 0 or completed_batches == total_batches:
                elapsed = time.time() - start_time
                pct = (completed_batches / total_batches) * 100.0
                print(f"  Progress: {completed_batches}/{total_batches} batches ({pct:.1f}%) | {total_classified} artists cached | {elapsed:.1f}s elapsed", flush=True)

    elapsed = time.time() - start_time
    print(f"Gemini enrichment complete: {total_classified} artist profiles cached in {elapsed:.1f}s.")
    return 0


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Enrich artists using Gemini Flash LLM")
    parser.add_argument("--scope", choices=["all", "gaps"], default="all", help="Scope of artists to classify")
    parser.add_argument("--min-plays", type=int, default=0, help="Minimum plays threshold")
    parser.add_argument("--limit", type=int, default=None, help="Max artists to process")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model slug")
    parser.add_argument("--workers", type=int, default=4, help="Parallel worker threads")
    args = parser.parse_args()

    con = duckdb.connect(str(config.MUSIC_DB), read_only=True)
    try:
        candidates = get_candidate_artists(con, min_plays=args.min_plays, scope=args.scope)
        print("Building evidence lookup across catalog...")
        evidence_lookup = build_evidence_lookup(con)
    finally:
        con.close()

    cache_path = config.CACHE_DIR / "http_cache.sqlite"
    cache = Cache(cache_path)
    try:
        run_enrichment(
            candidates,
            evidence_lookup,
            cache,
            model_id=args.model,
            limit=args.limit,
            workers=args.workers,
        )
    finally:
        cache.close()


if __name__ == "__main__":
    main()
