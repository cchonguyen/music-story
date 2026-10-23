"""W3 acceptance: enrichment clients, cache, queue order and cache parsing. No network."""

from __future__ import annotations

import json
import threading
import time

import duckdb
import httpx
import pytest
from helpers import fresh_db, scalar

from pipeline import enrich
from pipeline.enrich_cache import Cache
from pipeline.enrich_clients import Fetcher, RateLimited, build_request, cascade
from pipeline.enrich_queue import seed_queue, spotify_cap


def make_fetcher(handler, cache, api="deezer", sleeps=None, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    log = sleeps if sleeps is not None else []
    return Fetcher(api, client, cache, interval=0, sleep=log.append, **kwargs), log


def test_cache_hit_skips_request():
    cache = Cache(":memory:")
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={"id": 1})

    f, _ = make_fetcher(handler, cache)
    req = build_request("deezer", "track", "ISRC1")
    assert f.fetch("track", "ISRC1", req).from_cache is False
    assert f.fetch("track", "ISRC1", req).from_cache is True
    assert len(calls) == 1


def test_404_is_cached():
    cache = Cache(":memory:")
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(404, json={"error": "nope"})

    f, _ = make_fetcher(handler, cache, api="spotify")
    req = build_request("spotify", "tracks", "abc")
    assert f.fetch("tracks", "abc", req).status == 404
    assert f.fetch("tracks", "abc", req).from_cache is True
    assert len(calls) == 1
    assert cache.get("spotify", "tracks", "abc")[0] == 404


def test_429_honours_retry_after_then_succeeds():
    cache = Cache(":memory:")
    seen = []

    def handler(req):
        seen.append(1)
        if len(seen) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"id": 2})

    f, sleeps = make_fetcher(handler, cache)
    res = f.fetch("track", "K", build_request("deezer", "track", "K"))
    assert res.status == 200 and len(seen) == 2
    assert 7.0 in sleeps


def test_huge_retry_after_stops_the_api():
    cache = Cache(":memory:")
    f, _ = make_fetcher(lambda r: httpx.Response(429, headers={"Retry-After": "86400"}), cache)
    with pytest.raises(RateLimited):
        f.fetch("track", "K", build_request("deezer", "track", "K"))


def test_5xx_backs_off_then_records_error():
    cache = Cache(":memory:")
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503)

    f, sleeps = make_fetcher(handler, cache)
    cache.enqueue([("deezer", "track", "K", 1)])
    res = f.fetch("track", "K", build_request("deezer", "track", "K"))
    assert res.status is None and len(calls) == 5
    assert sleeps == [2.0, 4.0, 8.0, 16.0]
    assert cache.get("deezer", "track", "K") is None
    assert cache.next_item("deezer") is None  # failed items leave the eligible queue
    assert cache.status_counts()[0][4] == 1


def test_spotify_response_cascades_follow_ups():
    cache = Cache(":memory:")
    body = {"external_ids": {"isrc": "USX"}, "artists": [{"id": "ar1", "name": "A"}, {"id": "ar2"}]}
    f, _ = make_fetcher(lambda r: httpx.Response(200, json=body), cache, api="spotify")
    f.fetch("tracks", "t1", build_request("spotify", "tracks", "t1"), priority=3)
    queued = {(a, e, k, p) for a, e, k, p in cache.db.execute(
        "SELECT api, endpoint, key, priority FROM fetch_queue")}
    assert queued == {("spotify", "artists", "ar1", 3), ("musicbrainz", "isrc", "USX", 3),
                      ("deezer", "track", "USX", 3)}


def _events_db():
    con = fresh_db()
    rows = []  # (event_id, track_uri, artist_norm, full_norm, album_raw, track_mbid)
    for i in range(3):
        rows.append(("spotify:track:popular", "a", "pop", "Alb"))
    for i in range(2):
        rows.append(("spotify:track:middle", "a", "mid", "Alb"))
    rows.append(("spotify:track:rare", "b", "rare", None))
    rows.append((None, "c", "lfm", None, "mbid-1"))
    rows.append((None, "c", "lfm2", None))
    for n, r in enumerate(rows, 1):
        uri, artist, full, album = r[:4]
        mbid = r[4] if len(r) > 4 else None
        con.execute(
            "INSERT INTO events(event_id, source, started_at_utc, is_skip, track_uri, artist_raw, track_raw,"
            " album_raw, artist_norm, full_norm, base_norm, track_mbid) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [n, "spotify" if uri else "lastfm", "2024-01-01", False, uri, artist.upper(), full.upper(),
             album, artist, full, full, mbid],
        )
    return con


def test_queue_order_follows_play_count():
    con = _events_db()
    cache = Cache(":memory:")
    seed_queue(con, cache, {"spotify", "musicbrainz", "lastfm"})
    order = []
    while (item := cache.next_item("spotify")):
        order.append(item[1])
        cache.put("spotify", item[0], item[1], 404, "{}")
    assert order == ["popular", "middle", "rare"]
    assert cache.get("musicbrainz", "recording", "mbid-1") is None
    mb = {(e, k) for e, k in cache.db.execute("SELECT endpoint, key FROM fetch_queue WHERE api='musicbrainz'")}
    assert mb == {("recording", "mbid-1"), ("search", "c::lfm2")}
    lfm_tracks = [k for (k,) in cache.db.execute(
        "SELECT key FROM fetch_queue WHERE endpoint='track.getTopTags' ORDER BY priority")]
    assert lfm_tracks[:2] == ["a::pop", "a::mid"]
    # reseeding after work is done does not requeue cached items
    seed_queue(con, cache, {"spotify"})
    assert cache.next_item("spotify") is None


def put(cache, api, endpoint, key, status, body):
    cache.put(api, endpoint, key, status, json.dumps(body) if body is not None else None)


def test_run_fills_every_enr_table(tmp_path):
    cache_path = tmp_path / "c.sqlite"
    cache = Cache(cache_path)
    put(cache, "spotify", "tracks", "t1", 200, {
        "name": "Song", "duration_ms": 200000, "explicit": True, "external_ids": {"isrc": "USX1"},
        "album": {"id": "al1", "name": "Alb", "album_type": "album", "release_date": "2001-05",
                  "release_date_precision": "month"},
        "artists": [{"id": "ar1", "name": "Art"}]})
    put(cache, "spotify", "tracks", "gone", 404, {"error": {"status": 404}})
    put(cache, "spotify", "artists", "ar1", 200, {"name": "Art", "genres": ["rock", "pop"]})
    put(cache, "musicbrainz", "isrc", "USX1", 200, {"isrc": "USX1", "recordings": [
        {"id": "r2", "title": "Song", "length": 1, "first-release-date": "2005",
         "artist-credit": [{"name": "Art", "joinphrase": "", "artist": {"id": "m1", "name": "Art"}}]},
        {"id": "r1", "title": "Song", "length": 199000, "first-release-date": "2001-05-01",
         "artist-credit": [{"name": "Art", "joinphrase": "", "artist": {"id": "m1", "name": "Art"}}]}]})
    put(cache, "musicbrainz", "recording", "mb-r", 200, {
        "id": "mb-r", "title": "L", "length": 1000, "isrcs": ["USL1"], "genres": [{"name": "jazz"}],
        "first-release-date": "1999", "artist-credit": []})
    put(cache, "musicbrainz", "search", "x::y", 200, {"recordings": [
        {"id": "s1", "title": "Y", "score": 80, "artist-credit": []},
        {"id": "s2", "title": "Y", "score": 100, "artist-credit": []}]})
    put(cache, "musicbrainz", "artist", "m1", 200, {
        "id": "m1", "name": "Art", "type": "Group", "country": "GB",
        "life-span": {"begin": "1990-02-03", "end": None}, "genres": [{"name": "rock"}]})
    put(cache, "lastfm", "track.getTopTags", "art::song", 200,
        {"toptags": {"tag": [{"count": 100, "name": " Rock "}, {"count": 40, "name": "pop"}]}})
    put(cache, "lastfm", "artist.getTopTags", "art", 200, {"toptags": {"tag": {"count": 90, "name": "indie"}}})
    put(cache, "lastfm", "album.getTopTags", "art::alb", 200, {"toptags": {"tag": [{"count": 5, "name": "x"}]}})
    put(cache, "lastfm", "artist.getInfo", "art", 200,
        {"artist": {"mbid": "m1", "stats": {"listeners": "1000", "playcount": "9000"}}})
    put(cache, "lastfm", "track.getInfo", "x::y", 200,
        {"track": {"mbid": "", "listeners": "5", "playcount": "6", "duration": "0"}})
    put(cache, "lastfm", "track.getInfo", "x::z", 200,
        {"track": {"mbid": "", "listeners": "5", "playcount": "6", "duration": "180000"}})
    put(cache, "deezer", "track", "USX1", 200, {"id": 77, "bpm": 0, "gain": -9.5, "duration": 200,
                                                "release_date": "2001-05-01"})
    put(cache, "deezer", "track", "USX2", 200, {"error": {"code": 800}})
    cache.close()

    con = fresh_db()
    con.execute(
        "INSERT INTO stg_spotify(sp_id, started_at_utc, ended_at_utc, ms_played, is_full_listen, track_uri,"
        " reason_end, skipped) VALUES (1,'2024-01-01','2024-01-01',200000,true,'u1','trackdone',false),"
        "(2,'2024-01-01','2024-01-01',150000,true,'u1','trackdone',NULL),"
        "(3,'2024-01-01','2024-01-01',90000,true,'u1','fwdbtn',true),"
        "(4,'2024-01-01','2024-01-01',5,false,'u2','fwdbtn',true)"
    )
    enrich.run(con, cache_path)

    for table in ("enr_local_duration", "enr_spotify_track", "enr_spotify_artist", "enr_mb_recording",
                  "enr_mb_artist", "enr_lastfm_tags", "enr_lastfm_info", "enr_deezer_track"):
        assert scalar(con, f"SELECT count(*) FROM {table}") > 0, table
    assert con.execute("SELECT duration_ms, n_completed FROM enr_local_duration").fetchall() == [(200000, 2)]
    assert scalar(con, "SELECT count(*) FROM enr_spotify_track WHERE http_status=404 AND isrc IS NULL") == 1
    assert con.execute("SELECT artists[1].id, release_date_precision FROM enr_spotify_track "
                       "WHERE track_uri='spotify:track:t1'").fetchone() == ("ar1", "month")
    assert con.execute("SELECT recording_mbid, first_release_date FROM enr_mb_recording "
                       "WHERE lookup_kind='isrc'").fetchone() == ("r1", "2001-05-01")
    assert con.execute("SELECT recording_mbid, score FROM enr_mb_recording "
                       "WHERE lookup_kind='search'").fetchone() == ("s2", 100)
    assert con.execute("SELECT begin_year, end_year, country FROM enr_mb_artist").fetchone() == (1990, None, "GB")
    assert scalar(con, "SELECT count(*) FROM enr_lastfm_tags WHERE tag='rock' AND count=100") == 1
    assert scalar(con, "SELECT count(*) FROM enr_lastfm_tags WHERE entity_type='artist'") == 1
    assert scalar(con, "SELECT duration_ms FROM enr_lastfm_info WHERE entity_key='x::y'") is None
    assert scalar(con, "SELECT duration_ms FROM enr_lastfm_info WHERE entity_key='x::z'") == 180000
    assert scalar(con, "SELECT bpm FROM enr_deezer_track WHERE isrc='USX1'") is None
    assert scalar(con, "SELECT http_status FROM enr_deezer_track WHERE isrc='USX2'") == 404
    # running again is idempotent
    enrich.run(con, cache_path)
    assert scalar(con, "SELECT count(*) FROM enr_deezer_track") == 2


def test_run_with_empty_cache(tmp_path):
    con = fresh_db()
    enrich.run(con, tmp_path / "empty.sqlite")
    assert isinstance(con, duckdb.DuckDBPyConnection)
    assert scalar(con, "SELECT count(*) FROM enr_spotify_track") == 0


def run_worker_briefly(api, fetcher, cache, seconds=0.3):
    stop = threading.Event()
    w = enrich.Worker(api, fetcher, {}, stop)
    w.start()
    time.sleep(seconds)
    stop.set()
    w.join(2)
    return w


def test_long_lockout_is_stored_and_no_requests_follow():
    cache = Cache(":memory:")
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(429, headers={"Retry-After": "86400"})

    f, _ = make_fetcher(handler, cache)
    cache.enqueue([("deezer", "track", "ISRC1", 1), ("deezer", "track", "ISRC2", 2)])
    run_worker_briefly("deezer", f, cache)
    assert len(calls) == 1                       # asked once, then waited
    assert 86000 < cache.pause_left("deezer") <= 86400
    assert cache.pause_left("lastfm") == 0


def test_stored_lockout_blocks_a_new_run():
    cache = Cache(":memory:")
    cache.set_pause("deezer", 3600)
    calls = []
    f, _ = make_fetcher(lambda r: calls.append(r) or httpx.Response(200, json={}), cache)
    cache.enqueue([("deezer", "track", "ISRC1", 1)])
    w = run_worker_briefly("deezer", f, cache)
    assert calls == [] and w.paused


# ---- Spotify dev-mode quota: QUOTA_EXCEEDED, daily budget, play-count floor ----------------
QUOTA_BODY = {"error": {"status": 429, "message": "Too many requests", "reason": "QUOTA_EXCEEDED"}}


@pytest.mark.parametrize("body", [QUOTA_BODY, QUOTA_BODY["error"]])
def test_quota_exceeded_pauses_at_once_even_with_short_retry_after(body):
    cache = Cache(":memory:")
    calls = []
    f, sleeps = make_fetcher(lambda r: calls.append(r) or httpx.Response(
        429, headers={"Retry-After": "5"}, json=body), cache, api="spotify")
    with pytest.raises(RateLimited) as e:
        f.fetch("tracks", "t1", build_request("spotify", "tracks", "t1"))
    assert len(calls) == 1 and sleeps == []
    assert e.value.reason == "QUOTA_EXCEEDED" and e.value.seconds == 5


def test_quota_exceeded_without_retry_after_pauses_a_day():
    cache = Cache(":memory:")
    f, _ = make_fetcher(lambda r: httpx.Response(429, json=QUOTA_BODY), cache, api="spotify")
    with pytest.raises(RateLimited) as e:
        f.fetch("tracks", "t1", build_request("spotify", "tracks", "t1"))
    assert e.value.seconds == 86400


def test_spotify_bare_429_pauses_instead_of_retrying():
    cache = Cache(":memory:")
    calls = []
    f, _ = make_fetcher(lambda r: calls.append(r) or httpx.Response(429), cache, api="spotify")
    with pytest.raises(RateLimited) as e:
        f.fetch("tracks", "t1", build_request("spotify", "tracks", "t1"))
    assert len(calls) == 1 and e.value.seconds == 3600


def test_daily_budget_stops_before_the_next_request():
    cache = Cache(":memory:")
    calls = []
    f, _ = make_fetcher(lambda r: calls.append(r) or httpx.Response(200, json={}), cache,
                        api="spotify", budget=2)
    for k in ("a", "b"):
        f.fetch("tracks", k, build_request("spotify", "tracks", k))
    with pytest.raises(RateLimited) as e:
        f.fetch("tracks", "c", build_request("spotify", "tracks", "c"))
    assert len(calls) == 2 and e.value.reason == "budget"
    assert 86000 < e.value.seconds <= 86400
    assert cache.requests_in_window("spotify")[0] == 2


def test_worker_stores_the_pause_reason():
    cache = Cache(":memory:")
    f, _ = make_fetcher(lambda r: httpx.Response(429, json=QUOTA_BODY), cache, api="spotify")
    cache.enqueue([("spotify", "tracks", "t1", 1)])
    run_worker_briefly("spotify", f, cache)
    assert cache.pause_reason("spotify") == "QUOTA_EXCEEDED"
    assert cache.next_item("spotify") == ("tracks", "t1", 1)  # still queued, not failed


def test_play_count_floor_skips_rare_tracks_without_dropping_them():
    con = _events_db()
    cache = Cache(":memory:")
    seed_queue(con, cache, {"spotify"})
    assert spotify_cap(con, 2) == 2
    cache.set_limit("spotify", spotify_cap(con, 2), "min_plays=2")
    order = []
    while (item := cache.next_item("spotify")):
        order.append(item[1])
        cache.put("spotify", item[0], item[1], 404, "{}")
    assert order == ["popular", "middle"]
    assert cache.pending(["spotify"]) == 0 and cache.over_limit() == {"spotify": 1}
    cache.set_limit("spotify", None)
    assert cache.next_item("spotify")[1] == "rare"


def test_spotify_artists_are_held_by_default():
    cache = Cache(":memory:")
    cache.enqueue([("spotify", "artists", "ar1", 1), ("spotify", "tracks", "t9", 9)])
    cache.put("spotify", "tracks", "t9", 404, "{}")
    assert cache.next_item("spotify") is None and cache.pending(["spotify"]) == 0
    assert cache.held_counts() == {("spotify", "artists"): 1} and cache.over_limit() == {}


def test_spotify_artists_on_request_wait_for_every_track():
    cache = Cache(":memory:", held=set())
    cache.enqueue([("spotify", "artists", "ar1", 1), ("spotify", "tracks", "t9", 9)])
    assert cache.next_item("spotify") == ("tracks", "t9", 9)
    cache.put("spotify", "tracks", "t9", 404, "{}")
    assert cache.next_item("spotify") == ("artists", "ar1", 1)


def test_zero_budget_never_stops_but_still_counts():
    cache = Cache(":memory:")
    f, _ = make_fetcher(lambda r: httpx.Response(200, json={}), cache, api="spotify", budget=None)
    for k in ("a", "b", "c"):
        f.fetch("tracks", k, build_request("spotify", "tracks", k))
    assert cache.requests_in_window("spotify")[0] == 3


def test_cli_passes_spotify_flags(monkeypatch):
    seen = {}
    monkeypatch.setattr(enrich, "fetch", lambda apis, mm, **kw: seen.update(kw) or 0)
    enrich.main(["fetch", "--spotify-min-plays", "5", "--spotify-budget", "0", "--spotify-artists"])
    assert seen == {"spotify_min_plays": 5, "wait": False, "spotify_budget": 0, "spotify_artists": True}
    enrich.main(["fetch"])
    assert seen["spotify_min_plays"] == 3 and seen["spotify_budget"] == 500 and not seen["spotify_artists"]


def test_old_cache_gains_pause_reason(tmp_path):
    import sqlite3

    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE api_pause (api TEXT PRIMARY KEY, until_utc TEXT NOT NULL)")
    db.execute("INSERT INTO api_pause VALUES ('spotify', '2099-01-01T00:00:00')")
    db.commit()
    db.close()
    cache = Cache(path)
    assert cache.pause_left("spotify") > 0 and cache.pause_reason("spotify") is None
    cache.set_pause("spotify", 60, "budget")
    assert cache.pause_reason("spotify") == "budget"


def test_fetch_exits_when_only_paused_apis_remain(tmp_path, monkeypatch, capsys):
    db = tmp_path / "music.duckdb"
    con = _events_db()
    con.execute(f"ATTACH '{db}' AS f")
    con.execute(f"COPY FROM DATABASE {con.execute('SELECT current_database()').fetchone()[0]} TO f")
    con.close()
    monkeypatch.setattr(enrich.config, "MUSIC_DB", db)
    monkeypatch.setattr(enrich.config, "SPOTIFY_CLIENT_ID", "id")
    monkeypatch.setattr(enrich.config, "SPOTIFY_CLIENT_SECRET", "secret")
    cache_path = tmp_path / "c.sqlite"
    cache = Cache(cache_path)
    cache.set_pause("spotify", 3600, "QUOTA_EXCEEDED")
    cache.close()
    started = time.monotonic()
    assert enrich.fetch(["spotify"], max_minutes=1, cache_path=cache_path, spotify_min_plays=2) == 0
    out = capsys.readouterr().out
    assert time.monotonic() - started < 30
    assert "paused (QUOTA_EXCEEDED); rerun fetch after" in out
    assert "priority <= 2" in out


# ---- tail lookups by artist/title: Deezer search -> /track/{id} -> MusicBrainz ISRC ------------
DZ_SEARCH = {"data": [
    {"id": 11, "title": "Other Song", "artist": {"name": "A"}},
    {"id": 12, "title": "Song (Radio Edit)", "artist": {"name": "A"}},
    {"id": 13, "title": "Song", "artist": {"name": "A"}, "album": {"id": 5, "title": "Alb"}, "duration": 200},
]}
DZ_TRACK = {"id": 13, "isrc": "USDZ1", "bpm": 120, "gain": -8.1, "duration": 200, "release_date": "2004-02-01",
            "album": {"id": 5, "title": "Alb"}}


def test_deezer_search_request_and_cascade():
    req = build_request("deezer", "search", "a::song", {"track": {"a::song": ("A", 'So"ng')}})
    assert req.url == "https://api.deezer.com/search" and req.params["q"] == 'artist:"A" track:"So ng"'
    assert build_request("deezer", "id", "13").url == "https://api.deezer.com/track/13"
    assert cascade("deezer", "search", "a::song", 200, json.dumps(DZ_SEARCH), 7) == [("deezer", "id", "13", 7)]
    assert cascade("deezer", "search", "b::song", 200, json.dumps(DZ_SEARCH), 7) == []
    assert cascade("deezer", "id", "13", 200, json.dumps(DZ_TRACK), 7) == [("musicbrainz", "isrc", "USDZ1", 7)]
    assert cascade("deezer", "id", "13", 200, json.dumps({"error": {"code": 800}}), 7) == []


def test_deezer_quota_error_is_retried():
    cache = Cache(":memory:")
    seen = []

    def handler(req):
        seen.append(1)
        if len(seen) == 1:
            return httpx.Response(200, json={"error": {"type": "Exception", "code": 4}})
        return httpx.Response(200, json=DZ_TRACK)

    f, _ = make_fetcher(handler, cache)
    assert f.fetch("id", "13", build_request("deezer", "id", "13")).status == 200 and len(seen) == 2


def test_tail_under_the_floor_is_queued_for_search():
    con = _events_db()  # popular 3 plays, middle 2, rare 1 (all Spotify), plus two Last.fm-only keys
    cache = Cache(":memory:")
    seed_queue(con, cache, {"spotify", "musicbrainz", "deezer"}, spotify_min_plays=3)
    rows = {(a, e, k) for a, e, k in cache.db.execute(
        "SELECT api, endpoint, key FROM fetch_queue WHERE endpoint = 'search'")}
    assert rows == {("musicbrainz", "search", "a::mid"), ("musicbrainz", "search", "b::rare"),
                    ("musicbrainz", "search", "c::lfm2"), ("deezer", "search", "a::mid"),
                    ("deezer", "search", "b::rare"), ("deezer", "search", "c::lfm"),
                    ("deezer", "search", "c::lfm2")}
    order = []
    while (item := cache.next_item("deezer")):
        order.append(item[1])
        cache.put("deezer", item[0], item[1], 404, "{}")
    assert order[:2] == ["c::lfm", "c::lfm2"]  # Last.fm-only roots before the tail


def test_parse_builds_deezer_matches(tmp_path):
    cache = Cache(tmp_path / "c.sqlite")
    put(cache, "deezer", "search", "a::song", 200, DZ_SEARCH)
    put(cache, "deezer", "id", "13", 200, DZ_TRACK)
    put(cache, "deezer", "search", "b::none", 200, {"data": []})
    con = fresh_db()
    enrich.run(con, tmp_path / "c.sqlite")
    rows = con.execute("SELECT lookup_key, deezer_id, isrc, album_name, release_date, duration_ms, http_status "
                       "FROM enr_deezer_match ORDER BY 1").fetchall()
    assert rows == [("a::song", 13, "USDZ1", "Alb", "2004-02-01", 200000, 200),
                    ("b::none", None, None, None, None, None, 404)]
    assert con.execute("SELECT deezer_id, bpm FROM enr_deezer_track WHERE isrc = 'USDZ1'").fetchone() == (13, 120)
