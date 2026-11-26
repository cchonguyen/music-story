"""Wikidata ID bridge: maps artist_mbid -> Discogs artist IDs (P1953).

Caches results in http_cache.sqlite under:
  api="wikidata", endpoint="artist_discogs"
"""

from __future__ import annotations

import json
import logging
import sys
import time

import duckdb
import httpx

from pipeline import config
from pipeline.enrich_cache import Cache

logger = logging.getLogger(__name__)
SPARQL_URL = "https://query.wikidata.org/sparql"
USER_AGENT = f"music-story/0.1 ( {config.MUSICBRAINZ_CONTACT or 'set MUSICBRAINZ_CONTACT in .env'} )"
BATCH_SIZE = 100


def query_wikidata_batch(mbids: list[str]) -> dict[str, list[int]]:
    """Query Wikidata for a batch of MBIDs returning {mbid: [discogs_id_int, ...]}."""
    values_str = " ".join(f'"{m}"' for m in mbids)
    sparql = f"""
    SELECT ?mbid ?discogs_id WHERE {{
      VALUES ?mbid {{ {values_str} }}
      ?item wdt:P434 ?mbid .
      ?item wdt:P1953 ?discogs_id .
    }}
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}
    resp = httpx.get(SPARQL_URL, params={"query": sparql}, headers=headers, timeout=45.0)
    if resp.status_code != 200:
        logger.warning(f"Wikidata returned HTTP {resp.status_code}: {resp.text[:200]}")
        return {}

    data = resp.json()
    bindings = data.get("results", {}).get("bindings", [])
    mapping: dict[str, list[int]] = {}
    for b in bindings:
        m = b.get("mbid", {}).get("value")
        d_val = b.get("discogs_id", {}).get("value")
        if m and d_val:
            try:
                mapping.setdefault(m, []).append(int(d_val))
            except ValueError:
                continue
    return mapping


def run_bridge(con: duckdb.DuckDBPyConnection, cache: Cache, min_plays: int = 1) -> dict[int, str]:
    """Resolve all catalog artists with MBID to Discogs IDs, returning {discogs_artist_id: artist_norm}."""
    rows = con.execute("""
        SELECT a.artist_norm, a.artist_mbid, count(*) AS n
        FROM dim_artist a
        JOIN plays p USING (artist_id)
        WHERE a.artist_mbid IS NOT NULL
        GROUP BY 1, 2
        HAVING count(*) >= ?
        ORDER BY n DESC
    """, [min_plays]).fetchall()

    logger.info(f"Wikidata bridge: checking {len(rows)} artists with >= {min_plays} plays...")

    needed_mbids = []
    mbid_to_norms: dict[str, list[str]] = {}
    discogs_to_norm: dict[int, str] = {}

    for a_norm, mbid, _ in rows:
        mbid_to_norms.setdefault(mbid, []).append(a_norm)
        cached = cache.get("wikidata", "artist_discogs", a_norm)
        if cached is not None:
            _, body = cached
            if body:
                d = json.loads(body)
                for d_id in d.get("discogs_artist_ids", []):
                    discogs_to_norm[d_id] = a_norm
        else:
            needed_mbids.append(mbid)

    needed_mbids = list(set(needed_mbids))

    if needed_mbids:
        print(f"Wikidata bridge: fetching Discogs IDs for {len(needed_mbids)} MBIDs ({len(discogs_to_norm)} already cached)...")
        batches = [needed_mbids[i : i + BATCH_SIZE] for i in range(0, len(needed_mbids), BATCH_SIZE)]
        for idx, batch in enumerate(batches, 1):
            if idx % 5 == 1 or idx == len(batches):
                print(f"  Wikidata batch {idx}/{len(batches)} ({len(batch)} MBIDs)...", flush=True)
            try:
                res = query_wikidata_batch(batch)
                # Cache each artist associated with this batch
                for mbid in batch:
                    d_ids = sorted(set(res.get(mbid, [])))
                    body = json.dumps({"discogs_artist_ids": d_ids})
                    for a_norm in mbid_to_norms.get(mbid, []):
                        cache.put("wikidata", "artist_discogs", a_norm, 200, body, [])
                        for d_id in d_ids:
                            discogs_to_norm[d_id] = a_norm
                time.sleep(1.0)  # Friendly pacing to respect WDQS guidelines
            except Exception as e:  # noqa: BLE001
                print(f"  Error querying Wikidata batch {idx}: {e}", file=sys.stderr)

    print(f"Wikidata bridge complete: {len(discogs_to_norm)} Discogs artist IDs mapped to catalog artists.")
    return discogs_to_norm


def main() -> None:
    con = duckdb.connect(str(config.MUSIC_DB), read_only=True)
    cache = Cache(config.CACHE_DIR / "http_cache.sqlite")
    try:
        run_bridge(con, cache)
    finally:
        cache.close()
        con.close()


if __name__ == "__main__":
    main()
