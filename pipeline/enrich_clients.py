"""HTTP side of enrichment: request builders, rate limiting, retries, cascades.

Nothing here prints response bodies. All waiting goes through an injectable
`sleep` so tests run instantly.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from pipeline.enrich_cache import MAX_ATTEMPTS, Cache, QueueItem

TIMEOUT = httpx.Timeout(20.0, connect=10.0)
MAX_RETRY_AFTER = 600.0  # a longer lockout is stored in api_pause and waited out without requests
# Minimum seconds between requests per api.
# Spotify: 3 req/s drew a 24 h lockout after ~600 requests (2026-10-22), so 1 req/s.
INTERVALS = {"spotify": 1.0, "musicbrainz": 1.05, "lastfm": 0.25, "deezer": 0.11}
LASTFM_TRANSIENT_ERRORS = {8, 11, 16, 29}


class RateLimited(Exception):
    """Retry-After was longer than we are willing to sit out."""

    def __init__(self, api: str, seconds: float):
        super().__init__(f"{api} asked to wait {seconds:.0f}s")
        self.seconds = seconds


@dataclass
class Request:
    url: str
    params: dict | None = None
    method: str = "GET"
    headers: dict = field(default_factory=dict)
    data: dict | None = None


@dataclass
class Result:
    status: int | None  # None when every attempt failed
    body: str | None
    from_cache: bool = False
    error: str | None = None


# ---- request builders -------------------------------------------------------
def _lucene(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def build_request(api: str, endpoint: str, key: str, names: dict | None = None,
                  lastfm_key: str | None = None) -> Request:
    """names maps norm keys to the most common raw spelling:
    names['artist'][artist_norm] = artist_raw,
    names['track'][key] = (artist_raw, track_raw), names['album'][key] = (artist_raw, album_raw)."""
    names = names or {}
    if api == "spotify":
        return Request(f"https://api.spotify.com/v1/{endpoint}/{key}")
    if api == "musicbrainz":
        base = "https://musicbrainz.org/ws/2"
        if endpoint == "isrc":
            return Request(f"{base}/isrc/{key}?inc=artist-credits+releases&fmt=json")
        if endpoint == "recording":
            return Request(f"{base}/recording/{key}?inc=isrcs+artist-credits+releases+genres&fmt=json")
        if endpoint == "artist":
            return Request(f"{base}/artist/{key}?inc=genres&fmt=json")
        if endpoint == "search":
            artist, title = names.get("track", {}).get(key, tuple(key.split("::", 1)))
            q = f'recording:"{_lucene(title)}" AND artist:"{_lucene(artist)}"'
            return Request(f"{base}/recording", {"query": q, "limit": 5, "fmt": "json"})
    if api == "lastfm":
        params = {"method": endpoint, "api_key": lastfm_key, "autocorrect": 1, "format": "json"}
        if endpoint.startswith("track."):
            params["artist"], params["track"] = names.get("track", {}).get(key, tuple(key.split("::", 1)))
        elif endpoint.startswith("album."):
            params["artist"], params["album"] = names.get("album", {}).get(key, tuple(key.split("::", 1)))
        else:
            params["artist"] = names.get("artist", {}).get(key, key)
        return Request("https://ws.audioscrobbler.com/2.0/", params)
    if api == "deezer":
        return Request(f"https://api.deezer.com/track/isrc:{key}")
    raise ValueError(f"unknown request {api}/{endpoint}")


# ---- cascades: follow-up work discovered in a response ----------------------
def _json(body: str | None):
    try:
        return json.loads(body) if body else None
    except ValueError:
        return None


def cascade(api: str, endpoint: str, key: str, status: int, body: str | None,
            priority: int) -> list[QueueItem]:
    """Queue items implied by one stored response (same priority as its parent)."""
    if status != 200:
        return []
    data = _json(body)
    if not isinstance(data, dict):
        return []
    out: list[QueueItem] = []
    if api == "spotify" and endpoint == "tracks":
        artists = data.get("artists") or []
        if artists and artists[0].get("id"):
            out.append(("spotify", "artists", artists[0]["id"], priority))
        isrc = (data.get("external_ids") or {}).get("isrc")
        if isrc:
            out.append(("musicbrainz", "isrc", isrc, priority))
            out.append(("deezer", "track", isrc, priority))
    elif api == "musicbrainz" and endpoint in ("isrc", "recording"):
        recs = data.get("recordings") if endpoint == "isrc" else [data]
        for rec in (recs or [])[:1]:
            credits = rec.get("artist-credit") or []
            if credits and (credits[0].get("artist") or {}).get("id"):
                out.append(("musicbrainz", "artist", credits[0]["artist"]["id"], priority))
    return out


# ---- rate limiting and fetching ---------------------------------------------
class RateLimiter:
    def __init__(self, interval: float, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.interval, self.sleep, self.clock = interval, sleep, clock
        self.next_ok = 0.0
        self.lock = threading.Lock()

    def wait(self) -> None:
        with self.lock:
            now = self.clock()
            delay = self.next_ok - now
            self.next_ok = max(now, self.next_ok) + self.interval
        if delay > 0:
            self.sleep(delay)


class SpotifyAuth:
    """Client-credentials token, refreshed on expiry or after a 401."""

    def __init__(self, client: httpx.Client, client_id: str, client_secret: str,
                 clock: Callable[[], float] = time.monotonic):
        self.client, self.id, self.secret, self.clock = client, client_id, client_secret, clock
        self.token: str | None = None
        self.expires = 0.0

    def invalidate(self) -> None:
        self.token = None

    def headers(self) -> dict:
        if self.token is None or self.clock() >= self.expires:
            r = self.client.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "client_credentials"},
                auth=(self.id, self.secret),
            )
            r.raise_for_status()
            payload = r.json()
            self.token = payload["access_token"]
            self.expires = self.clock() + float(payload.get("expires_in", 3600)) - 60
        return {"Authorization": f"Bearer {self.token}"}


class Fetcher:
    """Cache-first fetching for one api with the retry rules from the spec."""

    def __init__(self, api: str, client: httpx.Client, cache: Cache, *, interval: float | None = None,
                 sleep: Callable[[float], None] = time.sleep, auth: SpotifyAuth | None = None,
                 user_agent: str | None = None):
        self.api, self.client, self.cache, self.sleep, self.auth = api, client, cache, sleep, auth
        self.limiter = RateLimiter(INTERVALS[api] if interval is None else interval, sleep)
        self.user_agent = user_agent

    def _transient_body(self, body: str) -> bool:
        if self.api != "lastfm":
            return False
        data = _json(body)
        return isinstance(data, dict) and data.get("error") in LASTFM_TRANSIENT_ERRORS

    def fetch(self, endpoint: str, key: str, req: Request, priority: int = 0) -> Result:
        hit = self.cache.get(self.api, endpoint, key)
        if hit is not None:
            return Result(hit[0], hit[1], from_cache=True)
        error = "no attempt"
        refreshed = False
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self.limiter.wait()
            headers = dict(req.headers)
            if self.user_agent:
                headers["User-Agent"] = self.user_agent
            if self.auth:
                headers.update(self.auth.headers())
            try:
                resp = self.client.request(req.method, req.url, params=req.params, headers=headers,
                                           data=req.data)
            except httpx.HTTPError as e:
                error = type(e).__name__
                if attempt < MAX_ATTEMPTS:
                    self.sleep(min(2.0**attempt, 60.0))
                continue
            status = resp.status_code
            if status == 401 and self.auth and not refreshed:
                refreshed = True
                self.auth.invalidate()
                continue
            if status == 429:
                try:
                    wait = float(resp.headers.get("Retry-After", ""))
                except ValueError:
                    wait = min(2.0**attempt, 60.0)
                if wait > MAX_RETRY_AFTER:
                    raise RateLimited(self.api, wait)
                error = "429"
                if attempt < MAX_ATTEMPTS:
                    self.sleep(wait)
                continue
            if status >= 500 or self._transient_body(resp.text):
                error = str(status)
                if attempt < MAX_ATTEMPTS:
                    self.sleep(min(2.0**attempt, 60.0))
                continue
            body = resp.text
            self.cache.put(self.api, endpoint, key, status, body,
                           cascade(self.api, endpoint, key, status, body, priority))
            return Result(status, body)
        self.cache.mark_failed(self.api, endpoint, key, error)
        return Result(None, None, error=error)
