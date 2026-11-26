"""Discogs CC0 masters dump downloader and streaming parser.

Streams discogs_YYYYMM01_masters.xml.gz from data.discogs.com,
matches against catalog Discogs artist IDs resolved via Wikidata,
and caches structured release genres & styles in http_cache.sqlite under:
  api="discogs", endpoint="artist_styles"
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx

from pipeline import config
from pipeline.enrich_cache import Cache

logger = logging.getLogger(__name__)

DISCOGS_BASE_URL = "https://data.discogs.com"
CHUNK_SIZE = 1024 * 1024 * 4  # 4 MB chunks


def get_latest_dump_url() -> str:
    """Find the latest available masters.xml.gz dump URL on data.discogs.com."""
    current_year = int(time.strftime("%Y"))
    links: list[str] = []
    index_url = ""
    for year in (current_year, current_year - 1):
        index_url = f"{DISCOGS_BASE_URL}/?prefix=data%2F{year}%2F"
        resp = httpx.get(index_url, follow_redirects=True, timeout=15.0)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch Discogs dump index: HTTP {resp.status_code}")
        links = re.findall(r'href=[\"\']([^\"\']*masters\.xml\.gz)[\"\']', resp.text)
        if links:
            break
    if not links:
        raise RuntimeError(f"No masters.xml.gz links found in {index_url}")

    latest_link = links[-1]
    if latest_link.startswith("http"):
        return latest_link
    if latest_link.startswith("/"):
        return f"{DISCOGS_BASE_URL}{latest_link}"
    return f"{DISCOGS_BASE_URL}/{latest_link}"


def load_discogs_targets(cache: Cache) -> dict[int, list[str]]:
    """Read cached Wikidata mappings to get {discogs_artist_id: [artist_norm, ...]}."""
    discogs_to_norms: dict[int, list[str]] = {}
    for artist_norm, _status, body, _at in cache.rows("wikidata", "artist_discogs"):
        if not body:
            continue
        try:
            d = json.loads(body)
            for d_id in d.get("discogs_artist_ids", []):
                aid = int(d_id)
                discogs_to_norms.setdefault(aid, []).append(artist_norm)
        except (json.JSONDecodeError, ValueError):
            continue

    # Deduplicate lists
    return {aid: sorted(set(norms)) for aid, norms in discogs_to_norms.items()}


def download_dump(url: str, dest_path: Path) -> None:
    """Download the compressed Discogs masters dump with streaming progress."""
    print(f"Downloading Discogs masters dump from {url}...")
    t0 = time.time()
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    with httpx.stream("GET", url, follow_redirects=True, timeout=120.0) as resp:
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to download dump: HTTP {resp.status_code}")
        total_bytes = int(resp.headers.get("content-length", 0))
        total_mb = total_bytes / (1024 * 1024) if total_bytes else 0

        downloaded = 0
        last_print = t0
        with open(dest_path, "wb") as out:
            for chunk in resp.iter_bytes(chunk_size=CHUNK_SIZE):
                out.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if now - last_print >= 5.0 or (total_bytes and downloaded >= total_bytes):
                    mb = downloaded / (1024 * 1024)
                    pct = (downloaded / total_bytes * 100) if total_bytes else 0.0
                    speed = mb / (now - t0) if now > t0 else 0.0
                    print(f"  Downloaded {mb:.1f} / {total_mb:.1f} MB ({pct:.1f}%) at {speed:.1f} MB/s...", flush=True)
                    last_print = now

    dur = time.time() - t0
    final_mb = dest_path.stat().st_size / (1024 * 1024)
    print(f"Download complete: {final_mb:.1f} MB in {dur:.1f}s.")


def parse_masters_dump(
    dump_path: Path, discogs_to_norms: dict[int, list[str]]
) -> dict[str, dict[str, Any]]:
    """Stream-parse the gzipped XML masters file, collecting styles for target artists."""
    target_ids = set(discogs_to_norms.keys())
    print(f"Stream-parsing Discogs masters for {len(target_ids)} target artist IDs...")
    t0 = time.time()

    # artist_norm -> {"discogs_id": int, "genres": Counter, "styles": Counter, "count": int}
    artist_results: dict[str, dict[str, Any]] = {}
    master_count = 0
    matched_masters = 0
    last_print = t0

    with gzip.open(dump_path, "rb") as f:
        context = ET.iterparse(f, events=("end",))
        for _, elem in context:
            if elem.tag == "master":
                master_count += 1
                artists_node = elem.find("artists")
                if artists_node is not None:
                    matched_in_release = []
                    for art in artists_node.findall("artist"):
                        aid_node = art.find("id")
                        if aid_node is not None and aid_node.text:
                            try:
                                aid = int(aid_node.text)
                                if aid in target_ids:
                                    matched_in_release.append(aid)
                            except ValueError:
                                pass

                    if matched_in_release:
                        matched_masters += 1
                        genres = [g.text.strip().lower() for g in elem.findall("genres/genre") if g.text]
                        styles = [s.text.strip().lower() for s in elem.findall("styles/style") if s.text]
                        for aid in matched_in_release:
                            for norm in discogs_to_norms.get(aid, []):
                                rec = artist_results.setdefault(
                                    norm,
                                    {"discogs_artist_id": aid, "genres": {}, "styles": {}, "master_count": 0},
                                )
                                rec["master_count"] += 1
                                for g in genres:
                                    rec["genres"][g] = rec["genres"].get(g, 0) + 1
                                for s in styles:
                                    rec["styles"][s] = rec["styles"].get(s, 0) + 1

                elem.clear()

                now = time.time()
                if now - last_print >= 10.0:
                    print(
                        f"  Scanned {master_count:,} masters | Matched {matched_masters:,} releases across {len(artist_results):,} catalog artists...",
                        flush=True,
                    )
                    last_print = now

    dur = time.time() - t0
    print(
        f"Parsing finished in {dur:.1f}s: {master_count:,} masters scanned, "
        f"{matched_masters:,} matched across {len(artist_results):,} artists."
    )
    return artist_results


def cache_results(cache: Cache, results: dict[str, dict[str, Any]]) -> int:
    """Store top styles and genres per artist in http_cache.sqlite."""
    saved = 0
    for artist_norm, data in results.items():
        # Sort genres and styles by count descending
        sorted_genres = [g for g, _ in sorted(data["genres"].items(), key=lambda x: x[1], reverse=True)]
        sorted_styles = [s for s, _ in sorted(data["styles"].items(), key=lambda x: x[1], reverse=True)]

        body = json.dumps(
            {
                "discogs_artist_id": data["discogs_artist_id"],
                "genres": sorted_genres,
                "styles": sorted_styles,
                "master_count": data["master_count"],
            },
            ensure_ascii=False,
        )
        cache.put("discogs", "artist_styles", artist_norm, 200, body, [])
        saved += 1
    return saved


def run(cache: Cache, dump_file: Path | None = None, keep_dump: bool = False) -> int:
    target_map = load_discogs_targets(cache)
    if not target_map:
        print("No target Discogs artist IDs found in cache. Run pipeline.enrich_wikidata first.", file=sys.stderr)
        return 1

    temp_path = dump_file or (Path(tempfile.gettempdir()) / "discogs_masters_dump.xml.gz")
    try:
        if not temp_path.exists():
            url = get_latest_dump_url()
            download_dump(url, temp_path)
        else:
            print(f"Using existing dump file at {temp_path} ({temp_path.stat().st_size / (1024*1024):.1f} MB)...")

        results = parse_masters_dump(temp_path, target_map)
        saved = cache_results(cache, results)
        print(f"Cached Discogs style profiles for {saved} artists in http_cache.sqlite.")
        return 0
    finally:
        if not keep_dump and temp_path.exists() and dump_file is None:
            print(f"Cleaning up temporary dump file {temp_path}...")
            temp_path.unlink(missing_ok=True)


def main() -> None:
    cache = Cache(config.CACHE_DIR / "http_cache.sqlite")
    try:
        run(cache)
    finally:
        cache.close()


if __name__ == "__main__":
    main()
