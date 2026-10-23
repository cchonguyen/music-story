"""SQLite HTTP cache and resumable work queue (schema: sql/cache_schema.sql).

One connection shared by the api worker threads, guarded by a lock. Every
mutation that belongs together (cache row, queue deletion, cascaded queue
items) happens in one transaction, so killing the process never loses a step.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pipeline import config

MAX_ATTEMPTS = 5

# (api, endpoint, key, priority)
QueueItem = tuple[str, str, str, int]


# fetch_queue row `q` is within its api's play-count floor (api_limit)
_WITHIN = "q.priority <= coalesce((SELECT max_priority FROM api_limit l WHERE l.api = q.api), q.priority)"
# 1 for endpoints that go after every other endpoint of their api
_DEFERRED = "(q.api = 'spotify' AND q.endpoint = 'artists')"


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S")


def utcnow_iso() -> str:
    return _iso(datetime.now(UTC))


def default_path() -> Path:
    return config.CACHE_DIR / "http_cache.sqlite"


class Cache:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_path()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.lock = threading.RLock()
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(config.CACHE_SCHEMA_SQL.read_text())
            cols = {r[1] for r in self.db.execute("PRAGMA table_info(api_pause)")}
            if "reason" not in cols:  # caches created before the column existed
                self.db.execute("ALTER TABLE api_pause ADD COLUMN reason TEXT")

    # ---- long lockouts ------------------------------------------------------
    def set_pause(self, api: str, seconds: float, reason: str | None = None) -> None:
        until = (datetime.now(UTC) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S")
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO api_pause(api, until_utc, reason) VALUES (?, ?, ?)",
                            (api, until, reason))

    def pause_reason(self, api: str) -> str | None:
        with self.lock:
            row = self.db.execute("SELECT reason FROM api_pause WHERE api = ?", (api,)).fetchone()
        return row[0] if row else None

    def pause_left(self, api: str) -> float:
        """Seconds until `api` may be asked again; 0 when it is not locked out."""
        with self.lock:
            row = self.db.execute("SELECT until_utc FROM api_pause WHERE api = ?", (api,)).fetchone()
        if row is None:
            return 0.0
        until = datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
        return max(0.0, (until - datetime.now(UTC)).total_seconds())

    # ---- daily request budget ---------------------------------------------
    def log_request(self, api: str) -> None:
        now = datetime.now(UTC)
        with self.lock:
            self.db.execute("INSERT INTO request_log(api, at_utc) VALUES (?, ?)", (api, _iso(now)))
            self.db.execute("DELETE FROM request_log WHERE api = ? AND at_utc < ?",
                            (api, _iso(now - timedelta(days=2))))

    def requests_in_window(self, api: str, window_s: float = 86400.0) -> tuple[int, float]:
        """(requests sent in the last `window_s`, seconds until the oldest of them ages out)."""
        now = datetime.now(UTC)
        with self.lock:
            n, oldest = self.db.execute(
                "SELECT count(*), min(at_utc) FROM request_log WHERE api = ? AND at_utc >= ?",
                (api, _iso(now - timedelta(seconds=window_s))),
            ).fetchone()
        if not n:
            return 0, 0.0
        ages_out = datetime.strptime(oldest, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC) \
            + timedelta(seconds=window_s)
        return n, max(0.0, (ages_out - now).total_seconds())

    # ---- play-count floor ---------------------------------------------------
    def set_limit(self, api: str, max_priority: int | None, note: str | None = None) -> None:
        with self.lock:
            if max_priority is None:
                self.db.execute("DELETE FROM api_limit WHERE api = ?", (api,))
            else:
                self.db.execute("INSERT OR REPLACE INTO api_limit(api, max_priority, note) VALUES (?, ?, ?)",
                                (api, max_priority, note))

    def limit(self, api: str) -> tuple[int, str | None] | None:
        with self.lock:
            return self.db.execute("SELECT max_priority, note FROM api_limit WHERE api = ?", (api,)).fetchone()

    def close(self) -> None:
        with self.lock:
            self.db.close()

    # ---- cache rows -------------------------------------------------------
    def get(self, api: str, endpoint: str, key: str) -> tuple[int, str | None] | None:
        with self.lock:
            return self.db.execute(
                "SELECT status, body FROM http_cache WHERE api=? AND endpoint=? AND key=?",
                (api, endpoint, key),
            ).fetchone()

    def put(self, api: str, endpoint: str, key: str, status: int, body: str | None,
            cascade: Iterable[QueueItem] = ()) -> None:
        """Store a response, drop its queue row and enqueue follow-up work, atomically."""
        with self.lock:
            self.db.execute("BEGIN")
            try:
                self.db.execute(
                    "INSERT OR REPLACE INTO http_cache(api, endpoint, key, status, body, fetched_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (api, endpoint, key, status, body, utcnow_iso()),
                )
                self.db.execute(
                    "DELETE FROM fetch_queue WHERE api=? AND endpoint=? AND key=?", (api, endpoint, key)
                )
                self._enqueue(cascade)
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    # ---- queue ------------------------------------------------------------
    def _enqueue(self, items: Iterable[QueueItem]) -> None:
        self.db.executemany(
            "INSERT OR IGNORE INTO fetch_queue(api, endpoint, key, priority) "
            "SELECT ?,?,?,? WHERE NOT EXISTS "
            "(SELECT 1 FROM http_cache c WHERE c.api=? AND c.endpoint=? AND c.key=?)",
            [(a, e, k, p, a, e, k) for a, e, k, p in items],
        )

    def enqueue(self, items: Iterable[QueueItem]) -> None:
        with self.lock:
            self.db.execute("BEGIN")
            try:
                self._enqueue(items)
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def next_item(self, api: str) -> tuple[str, str, int] | None:
        """Highest-priority eligible queue row as (endpoint, key, priority).
        Within the api's limit; Spotify artists wait until no track is left."""
        with self.lock:
            return self.db.execute(
                f"SELECT endpoint, key, priority FROM fetch_queue q WHERE api=? AND attempts<? AND {_WITHIN} "
                f"ORDER BY {_DEFERRED}, priority, endpoint, key LIMIT 1",
                (api, MAX_ATTEMPTS),
            ).fetchone()

    def mark_failed(self, api: str, endpoint: str, key: str, error: str) -> None:
        with self.lock:
            self.db.execute(
                "UPDATE fetch_queue SET attempts=?, last_error=? WHERE api=? AND endpoint=? AND key=?",
                (MAX_ATTEMPTS, error[:200], api, endpoint, key),
            )

    def reset_failed(self) -> None:
        """A new run gives previously failed items one more round."""
        with self.lock:
            self.db.execute("UPDATE fetch_queue SET attempts=0 WHERE attempts>=?", (MAX_ATTEMPTS,))

    def pending(self, apis: Iterable[str] | None = None) -> int:
        with self.lock:
            rows = self.db.execute(
                f"SELECT api, count(*) FROM fetch_queue q WHERE attempts<? AND {_WITHIN} GROUP BY api",
                (MAX_ATTEMPTS,),
            ).fetchall()
        wanted = set(apis) if apis is not None else None
        return sum(n for a, n in rows if wanted is None or a in wanted)

    def status_counts(self) -> list[tuple[str, str, int, int, int]]:
        """(api, endpoint, done, queued, failed) for every endpoint seen."""
        with self.lock:
            done = {(a, e): n for a, e, n in
                    self.db.execute("SELECT api, endpoint, count(*) FROM http_cache GROUP BY 1,2")}
            queued: dict[tuple[str, str], int] = {}
            failed: dict[tuple[str, str], int] = {}
            for a, e, n, f in self.db.execute(
                "SELECT api, endpoint, sum(attempts<?), sum(attempts>=?) FROM fetch_queue GROUP BY 1,2",
                (MAX_ATTEMPTS, MAX_ATTEMPTS),
            ):
                queued[(a, e)] = n
                failed[(a, e)] = f
        keys = sorted(set(done) | set(queued))
        return [(a, e, done.get((a, e), 0), queued.get((a, e), 0), failed.get((a, e), 0)) for a, e in keys]

    def over_limit(self) -> dict[str, int]:
        """Queued rows per api that sit past its play-count floor."""
        with self.lock:
            return dict(self.db.execute(
                f"SELECT api, count(*) FROM fetch_queue q WHERE attempts<? AND NOT {_WITHIN} GROUP BY api",
                (MAX_ATTEMPTS,),
            ).fetchall())

    # ---- reading for the parser -------------------------------------------
    def rows(self, api: str, endpoint: str) -> Iterator[tuple[str, int, str | None, str]]:
        """(key, status, body, fetched_at) for one endpoint."""
        with self.lock:
            data = self.db.execute(
                "SELECT key, status, body, fetched_at FROM http_cache WHERE api=? AND endpoint=?",
                (api, endpoint),
            ).fetchall()
        yield from data
