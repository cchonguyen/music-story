"""Build step 03 and the overnight fetch.

    uv run python -m pipeline.enrich fetch [--api spotify,musicbrainz,lastfm,deezer] [--max-minutes N]
    uv run python -m pipeline.enrich status

`run(con)` only parses the HTTP cache into the enr_* tables; it never touches the network.
`fetch` is resumable: the queue lives in the cache database. It prints counts, never bodies.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from datetime import datetime, timedelta

import duckdb
import httpx

from pipeline import config
from pipeline.enrich_cache import Cache
from pipeline.enrich_clients import (
    INTERVALS,
    TIMEOUT,
    Fetcher,
    RateLimited,
    SpotifyAuth,
    build_request,
)
from pipeline.enrich_parse import local_durations, parse_cache
from pipeline.enrich_queue import load_names, seed_queue

ALL_APIS = ["spotify", "musicbrainz", "lastfm", "deezer"]


def run(con: duckdb.DuckDBPyConnection, cache_path=None) -> None:
    """Build step 03: local durations plus the parsed cache. No network."""
    local_durations(con)
    path = cache_path or config.CACHE_DIR / "http_cache.sqlite"
    cache = Cache(path)
    try:
        parse_cache(con, cache)
    finally:
        cache.close()


class Worker(threading.Thread):
    """Works one api's queue in priority order until told to stop."""

    def __init__(self, api: str, fetcher: Fetcher, names: dict, stop: threading.Event,
                 lastfm_key: str | None = None):
        super().__init__(daemon=True, name=f"enrich-{api}")
        self.api, self.fetcher, self.names, self.stop_event = api, fetcher, names, stop
        self.lastfm_key = lastfm_key
        self.idle = False
        self.paused = False
        self.done = 0
        self.note: str | None = None

    def run(self) -> None:
        cache = self.fetcher.cache
        while not self.stop_event.is_set():
            wait = cache.pause_left(self.api)
            if wait > 0:  # locked out: send nothing until the stored time
                if not self.paused:
                    self.paused = True
                    resume = datetime.now().astimezone() + timedelta(seconds=wait)
                    print(f"{self.api}: locked out by the api, waiting until {resume:%a %H:%M} local "
                          "(no requests until then)", flush=True)
                self.idle = True
                self.stop_event.wait(min(wait, 60.0))
                continue
            if self.paused:
                self.paused = False
                print(f"{self.api}: lockout over, resuming", flush=True)
            item = cache.next_item(self.api)
            if item is None:
                self.idle = True
                self.stop_event.wait(1.0)
                continue
            self.idle = False
            endpoint, key, priority = item
            req = build_request(self.api, endpoint, key, self.names, self.lastfm_key)
            try:
                self.fetcher.fetch(endpoint, key, req, priority)
            except RateLimited as e:
                cache.set_pause(self.api, e.seconds)  # remembered across runs; the loop above waits
                self.note = str(e)
                continue
            except Exception as e:  # noqa: BLE001 - keep the overnight job alive; record and move on
                cache.mark_failed(self.api, endpoint, key, type(e).__name__)
            self.done += 1
        self.idle = True


def make_fetchers(apis: list[str], cache: Cache, client_factory=httpx.Client) -> dict[str, Fetcher]:
    fetchers: dict[str, Fetcher] = {}
    for api in apis:
        kwargs: dict = {}
        if api == "spotify":
            if not (config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET):
                print("spotify: SPOTIFY_CLIENT_ID/SECRET not set, skipping")
                continue
            client = client_factory(timeout=TIMEOUT)
            kwargs["auth"] = SpotifyAuth(client, config.SPOTIFY_CLIENT_ID, config.SPOTIFY_CLIENT_SECRET)
        elif api == "musicbrainz":
            if not config.MUSICBRAINZ_CONTACT:
                print("musicbrainz: MUSICBRAINZ_CONTACT not set, skipping")
                continue
            client = client_factory(timeout=TIMEOUT)
            kwargs["user_agent"] = f"music-story/0.1 ( {config.MUSICBRAINZ_CONTACT} )"
        elif api == "lastfm":
            if not config.LASTFM_API_KEY:
                print("lastfm: LASTFM_API_KEY not set, skipping")
                continue
            client = client_factory(timeout=TIMEOUT)
        else:
            client = client_factory(timeout=TIMEOUT)
        fetchers[api] = Fetcher(api, client, cache, **kwargs)
    return fetchers


def progress_line(cache: Cache, started: float) -> str:
    parts = []
    for api, endpoint, done, queued, failed in cache.status_counts():
        parts.append(f"{api}.{endpoint} {done}/{done + queued + failed}" + (f" failed {failed}" if failed else ""))
    return f"[{(time.monotonic() - started) / 60:.0f} min] " + "; ".join(parts)


def fetch(apis: list[str], max_minutes: float | None, cache_path=None, interval_s: float = 60.0) -> int:
    if not config.MUSIC_DB or not config.MUSIC_DB.exists():
        print("MUSIC_DB not found. Run build_pipeline --to 02 first.", file=sys.stderr)
        return 2
    con = duckdb.connect(str(config.MUSIC_DB), read_only=True)
    try:
        con.execute("SELECT 1 FROM events LIMIT 1")
    except duckdb.Error:
        print("events table missing. Run build_pipeline --to 02 first.", file=sys.stderr)
        return 2
    cache = Cache(cache_path)
    cache.reset_failed()
    fetchers = make_fetchers(apis, cache)
    if not fetchers:
        return 2
    offered = seed_queue(con, cache, set(fetchers))
    names = load_names(con)
    con.close()
    print("seeded " + ", ".join(f"{a}.{e} {n}" for (a, e), n in offered.items()))

    stop = threading.Event()
    workers = [Worker(a, f, names, stop, config.LASTFM_API_KEY) for a, f in fetchers.items()]
    started = time.monotonic()
    for w in workers:
        w.start()
    last_print = started
    try:
        while True:
            time.sleep(1.0)
            elapsed_min = (time.monotonic() - started) / 60
            live = [w for w in workers if w.is_alive()]
            if cache.pending(fetchers) == 0 and all(w.idle for w in workers):
                break
            if not live:
                break
            if max_minutes is not None and elapsed_min >= max_minutes:
                print("max-minutes reached, stopping")
                break
            if time.monotonic() - last_print >= interval_s:
                last_print = time.monotonic()
                print(progress_line(cache, started), flush=True)
    except KeyboardInterrupt:
        print("interrupted, stopping")
    stop.set()
    for w in workers:
        w.join(timeout=30)
        if w.note:
            print(f"{w.api}: {w.note}; stopped for this run")
    print(progress_line(cache, started))
    cache.close()
    return 0


def status(cache_path=None) -> int:
    cache = Cache(cache_path)
    rows = cache.status_counts()
    print(f"{'api':<12} {'endpoint':<20} {'done':>8} {'queued':>8} {'failed':>7}")
    queued_by_api: dict[str, int] = {}
    for api, endpoint, done, queued, failed in rows:
        print(f"{api:<12} {endpoint:<20} {done:>8} {queued:>8} {failed:>7}")
        queued_by_api[api] = queued_by_api.get(api, 0) + queued
    print("estimated hours left (queued / rate, ignores items queued by later responses):")
    for api, n in queued_by_api.items():
        wait = cache.pause_left(api)
        locked = ""
        if wait > 0:
            resume = datetime.now().astimezone() + timedelta(seconds=wait)
            locked = f"  (locked out until {resume:%a %H:%M} local, then)"
        print(f"  {api:<12} {n * INTERVALS[api] / 3600:6.1f} h{locked}")
    cache.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="work the queue, resumable")
    f.add_argument("--api", default=",".join(ALL_APIS), help="comma-separated subset")
    f.add_argument("--max-minutes", type=float, default=None)
    sub.add_parser("status", help="done / queued / failed per api and endpoint")
    args = ap.parse_args(argv)
    if args.cmd == "status":
        return status()
    apis = [a.strip() for a in args.api.split(",") if a.strip()]
    bad = [a for a in apis if a not in ALL_APIS]
    if bad:
        ap.error(f"unknown api: {','.join(bad)}")
    return fetch(apis, args.max_minutes)


if __name__ == "__main__":
    raise SystemExit(main())
