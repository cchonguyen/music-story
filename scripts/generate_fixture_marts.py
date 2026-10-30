#!/usr/bin/env python3
"""Pure-stdlib single-pass fixture mart generator & cache builder for container environments.
Imports Gen(SEED=20260422) directly from scripts/make_fixtures.py so every artist, track,
scenario, timestamp, and metric is bit-for-bit faithful to the DuckDB fixture."""

from __future__ import annotations

import datetime as dt
import json
import statistics
import sys
import types
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

if not hasattr(dt, "UTC"):
    dt.UTC = timezone.utc
UTC = timezone.utc

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Provide lightweight module stubs if duckdb/polars/dotenv are not installed in the container Python
for mod_name in ("duckdb", "polars"):
    if mod_name not in sys.modules:
        try:
            __import__(mod_name)
        except ImportError:
            sys.modules[mod_name] = types.ModuleType(mod_name)

try:
    import dotenv  # noqa: F401
except ImportError:
    stub_dotenv = types.ModuleType("dotenv")
    stub_dotenv.load_dotenv = lambda *a, **kw: None
    sys.modules["dotenv"] = stub_dotenv

from scripts.make_fixtures import (  # noqa: E402
    GENRE_BPM,
    LASTFM_ONLY_ID_OFFSET,
    PLATFORMS,
    TZ,
    ZZ_BLOCK,
    Gen,
    iso,
    platform_family,
)

CACHE_DIR = REPO_ROOT / "build" / "marts_cache"


def quantile_cont(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    if len(s) == 1:
        return float(s[0])
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return float(s[lo] * (1.0 - frac) + s[hi] * frac)


def build_all_marts() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    marker = CACHE_DIR / "_ready.json"
    if marker.exists() and (CACHE_DIR / "year.json").exists() and (CACHE_DIR / "explorer_events.json").exists():
        return

    g = Gen()
    g.build_catalog()
    listens = g.simulate()
    g.observe_lastfm(listens)
    r = g.r

    p_dt = lambda t: datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ")

    # 1. Observed Spotify & Last.fm rows (matching make_fixtures.py exact RNG consumption)
    sp_rows: list[dict] = []
    sp_of_listen: dict[int, dict] = {}
    for idx, li in enumerate(listens):
        if not li.on_spotify:
            continue
        ts = li.true_start + timedelta(milliseconds=li.ms_played) + timedelta(seconds=li.pause_s)
        ts = ts.replace(microsecond=0)
        d = li.true_start.date()
        conn = li.country
        if ZZ_BLOCK[0] <= d <= ZZ_BLOCK[1]:
            conn = "ZZ"
        elif r.random() < 0.005:
            conn = "ZZ"
        a = g.artists[li.rec.artist]
        alb = g.albums[dict(li.rec.uris)[li.uri]]
        row = {
            "ts": iso(ts),
            "platform": li.platform,
            "ms_played": li.ms_played,
            "conn_country": conn,
            "ip_addr": "203.0.113." + str(r.randint(1, 254)),
            "master_metadata_track_name": li.rec.spotify_title(g.artists),
            "master_metadata_album_artist_name": a.name,
            "master_metadata_album_album_name": alb.name,
            "spotify_track_uri": li.uri,
            "reason_start": li.reason_start,
            "reason_end": li.reason_end,
            "shuffle": li.shuffle,
            "skipped": li.skipped,
            "offline": li.offline,
            "incognito_mode": li.incognito,
        }
        sp_rows.append(row)
        sp_of_listen[idx] = row

    for _ in range(40):
        g.b62(22)

    lfm_rows: list[dict] = []
    lfm_of_listen: dict[int, dict] = {}
    for idx, li in enumerate(listens):
        if li.scrobble_t is None:
            continue
        rec = li.rec
        a = g.artists[rec.artist]
        alb = g.albums[rec.uris[0][1]]
        title = li.lfm_title if li.lfm_variant == "same" else rec.base_title
        base = {
            "artist": li.lfm_artist,
            "artist_mbid": a.mbid or "",
            "album": alb.name,
            "album_mbid": alb.mbid or "",
            "track": title,
            "track_mbid": rec.mbid or "",
        }
        row = dict(uts=int(li.scrobble_t.replace(tzinfo=UTC).timestamp()), **base)
        lfm_rows.append(row)
        lfm_of_listen[idx] = row
        if li.dupe_t is not None:
            dupe = dict(uts=int(li.dupe_t.replace(tzinfo=UTC).timestamp()), **base)
            lfm_rows.append(dupe)

    # Number & self-dedupe Last.fm rows
    lfm_sorted = sorted(lfm_rows, key=lambda x: (x["uts"], x["artist"], x["track"], x["album"]))
    lfm_id_map: dict[tuple[int, str, str], int] = {}
    by_pair: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    for i, row in enumerate(lfm_sorted, 1):
        lfm_id_map[(row["uts"], row["artist"], row["track"])] = i
        by_pair[(row["artist"], row["track"])].append((row["uts"], i))

    deduped: set[int] = set()
    for _, items in by_pair.items():
        for j in range(1, len(items)):
            if items[j][0] - items[j - 1][0] <= 60:
                deduped.add(items[j][1])

    sp_sorted = sorted(
        sp_rows,
        key=lambda x: (x["ts"], x["spotify_track_uri"], x["ms_played"], f"Streaming_History_Audio_{x['ts'][:4]}.json"),
    )
    sp_id_map = {(x["ts"], x["spotify_track_uri"], x["ms_played"]): i for i, x in enumerate(sp_sorted, 1)}

    links: dict[int, tuple[int, int, int, float, float]] = {}
    for idx, li in enumerate(listens):
        if idx in sp_of_listen and idx in lfm_of_listen:
            s, lrow = sp_of_listen[idx], lfm_of_listen[idx]
            ts = p_dt(s["ts"])
            start = ts - timedelta(milliseconds=s["ms_played"])
            gap = lrow["uts"] - start.replace(tzinfo=UTC).timestamp()
            if li.lfm_variant == "same":
                ok, mpass = -180 <= gap <= (ts - start).total_seconds() + 180, 1
            else:
                ok, mpass = abs(gap) <= 90, 2
            lid_ = lfm_id_map[(lrow["uts"], lrow["artist"], lrow["track"])]
            if ok and lid_ not in deduped:
                links[idx] = (
                    sp_id_map[(s["ts"], s["spotify_track_uri"], s["ms_played"])],
                    lid_,
                    mpass,
                    gap,
                    100.0,
                )

    A, AL, R = g.artists, g.albums, g.recs
    rec_year = {rid: min(int(AL[alb].release_date[:4]) for _, alb in rec.uris) for rid, rec in R.items()}
    work_year_map: dict[tuple[int, str], int] = {}
    for rid, rec in R.items():
        k = (rec.artist, rec.base_norm)
        work_year_map[k] = min(work_year_map.get(k, 9999), rec_year[rid])

    def is_longform(rec) -> bool:
        kw = any(k in rec.full_norm.split() for k in ("mix", "set", "live"))
        return rec.duration_ms > 1_200_000 or (rec.duration_ms > 600_000 and kw)

    # Events, country imputation, and sessions
    linked_lfm = {v[1] for v in links.values()}
    ev = []
    for idx, li in enumerate(listens):
        rec, a = li.rec, A[li.rec.artist]
        s = sp_of_listen.get(idx)
        lrow = lfm_of_listen.get(idx)
        lid = lfm_id_map[(lrow["uts"], lrow["artist"], lrow["track"])] if lrow else None
        if lid in deduped:
            lid = None
        base = {"rec": rec, "artist": a, "listen": li, "idx": idx}
        if s is not None:
            sid = sp_id_map[(s["ts"], s["spotify_track_uri"], s["ms_played"])]
            linked = idx in links
            end = p_dt(s["ts"])
            ev.append(
                dict(
                    base,
                    event_id=sid,
                    sp_id=sid,
                    lfm_id=lid if linked else None,
                    source="both" if linked else "spotify",
                    start=end - timedelta(milliseconds=s["ms_played"]),
                    end=end,
                    ms=s["ms_played"],
                    conn=s["conn_country"],
                    row=s,
                    match=links.get(idx),
                )
            )
        if lid is not None and lid not in linked_lfm:
            start = datetime.fromtimestamp(lrow["uts"], UTC).replace(tzinfo=None)
            ev.append(
                dict(
                    base,
                    event_id=LASTFM_ONLY_ID_OFFSET + lid,
                    sp_id=None,
                    lfm_id=lid,
                    source="lastfm",
                    start=start,
                    end=start + timedelta(milliseconds=rec.duration_ms),
                    ms=None,
                    conn=None,
                    row=None,
                    match=None,
                )
            )
    ev.sort(key=lambda e: (e["start"], e["event_id"]))
    for e in ev:
        e["is_skip"] = e["source"] == "spotify" and e["ms"] < 30_000

    sp_ev = [e for e in ev if e["conn"] is not None]
    known = [(e["start"], None if e["conn"] == "ZZ" else e["conn"]) for e in sp_ev]
    prev_known = []
    last = None
    for t, c in known:
        prev_known.append(last)
        if c:
            last = (t, c)
    next_known = [None] * len(known)
    last = None
    for i in range(len(known) - 1, -1, -1):
        next_known[i] = last
        if known[i][1]:
            last = known[i]
    for i, e in enumerate(sp_ev):
        c = known[i][1]
        e["country"], e["imputed"] = c, False
        if c is None:
            a_, b_ = prev_known[i], next_known[i]
            win = timedelta(hours=48)
            if a_ and b_ and a_[1] == b_[1] and e["start"] - a_[0] <= win and b_[0] - e["start"] <= win:
                e["country"], e["imputed"] = a_[1], True
    for e in ev:
        e.setdefault("country", None)
        e.setdefault("imputed", False)
        e["tz"] = TZ.get(e["country"] or "US", TZ["US"])
        e["local"] = e["start"].replace(tzinfo=UTC).astimezone(ZoneInfo(e["tz"])).replace(tzinfo=None)

    sid, run_end, idx_in = 0, None, 0
    sess: dict[int, list[dict]] = defaultdict(list)
    for e in ev:
        gap = None if run_end is None else (e["start"] - run_end).total_seconds()
        if gap is None or gap > 1200:
            sid += 1
            idx_in = 0
        idx_in += 1
        e["session_id"], e["session_index"] = sid, idx_in
        e["new10"] = gap is None or gap > 600
        e["new30"] = gap is None or gap > 1800
        run_end = e["end"] if run_end is None else max(run_end, e["end"])
        sess[sid].append(e)

    long_ids = {rid for rid, rec in R.items() if is_longform(rec)}
    ratios = [
        e["ms"] / e["rec"].duration_ms
        for e in ev
        if e["sp_id"] and e["ms"] >= 30_000 and e["rec"].rid not in long_ids
    ]
    median_completion = statistics.median(ratios)

    plays_list = []
    skips_list = []
    for e in ev:
        rec = e["rec"]
        row = e["row"]
        ms_imp = e["ms"] if e["ms"] is not None else int(rec.duration_ms * median_completion)
        ratio = None if e["ms"] is None or rec.rid in long_ids else min(e["ms"] / rec.duration_ms, 1.0)
        item = {
            "play_id": e["event_id"],
            "started_at_utc": e["start"],
            "ended_at_utc": e["end"],
            "started_at_local": e["local"],
            "year": e["local"].year,
            "weekday": e["local"].isoweekday(),
            "hour": e["local"].hour,
            "date": e["local"].date(),
            "country": e["country"],
            "country_imputed": e["imputed"],
            "track_id": rec.isrc,
            "rec": rec,
            "artist_id": rec.artist,
            "album_id": rec.uris[0][1] if row is None else dict(rec.uris)[row["spotify_track_uri"]],
            "session_id": e["session_id"],
            "session_index": e["session_index"],
            "new_session_10": e["new10"],
            "new_session_30": e["new30"],
            "ms_played": e["ms"],
            "ms_imputed": ms_imp,
            "completion_ratio": ratio,
            "source": e["source"],
            "platform_family": platform_family(row["platform"]) if row else None,
            "shuffle": row["shuffle"] if row else None,
            "reason_start": (row["reason_start"] or None) if row else None,
            "reason_end": (row["reason_end"] or None) if row else None,
            "is_skip": e["is_skip"],
        }
        if e["is_skip"]:
            skips_list.append(item)
        else:
            plays_list.append(item)

    # Advance RNG for sp_tracks and sp_artist to match make_fixtures.py stream before dz
    sp_ = g.special
    scenario_rids = {
        sp_["binge"],
        sp_["djmix"],
        sp_["longtrack"],
        sp_["glass"],
        sp_["paper"],
        sp_["remaster"],
        *sp_["remix_recs"],
    }
    for rec in R.values():
        for _ in rec.uris:
            if r.random() < 0.02 and rec.rid not in scenario_rids:
                continue
    for _ in A.values():
        r.random()

    dz_map: dict[str, tuple[float, float]] = {}
    for rec in R.values():
        if r.random() < 0.6:
            bpm = GENRE_BPM[A[rec.artist].genre] + r.uniform(-6, 6)
            bpm = None if r.random() < 0.1 else (bpm * 2 if r.random() < 0.05 else bpm)
            _ = r.randint(1, 10**9)
            gain = r.uniform(-12, -4)
            if bpm is not None and bpm > 0:
                bpm_clean = bpm / 2.0 if bpm > 175 else (bpm * 2.0 if bpm < 55 else bpm)
                dz_map[rec.isrc] = (bpm_clean, gain)

    parent_map = {
        "indie rock": "rock",
        "electro house": "electronic",
        "dubstep": "electronic",
        "house": "electronic",
        "techno": "electronic",
        "ambient": "electronic",
        "hip hop": "hip hop",
        "k-pop": "pop",
        "v-pop": "pop",
        "j-pop": "pop",
    }

    # --- Mart 1: year.json ---
    first_artist_year: dict[int, int] = {}
    first_track_year: dict[str, int] = {}
    for p in sorted(plays_list, key=lambda x: x["started_at_utc"]):
        first_artist_year.setdefault(p["artist_id"], p["year"])
        first_track_year.setdefault(p["track_id"], p["year"])

    new_artists_by_y = Counter(first_artist_year.values())
    new_tracks_by_y = Counter(first_track_year.values())
    skips_by_y = Counter(s["year"] for s in skips_list)
    sess_by_y = Counter(es[0]["local"].year for es in sess.values())

    plays_by_y: dict[int, list[dict]] = defaultdict(list)
    for p in plays_list:
        plays_by_y[p["year"]].append(p)

    mart_year = []
    for y in sorted(plays_by_y):
        ps = plays_by_y[y]
        mart_year.append(
            {
                "year": y,
                "plays": len(ps),
                "skips": skips_by_y[y],
                "listen_hours": sum(x["ms_imputed"] for x in ps) / 3.6e6,
                "artists": len({x["artist_id"] for x in ps}),
                "tracks": len({x["track_id"] for x in ps}),
                "new_artists": new_artists_by_y[y],
                "new_tracks": new_tracks_by_y[y],
                "sessions": sess_by_y[y],
            }
        )

    # --- Mart 2 & 3: artist_year.json & track_year.json (filtered rank <= 50) ---
    mart_artist_year_all = []
    mart_track_year_all = []
    for y in sorted(plays_by_y):
        ps = plays_by_y[y]
        by_a: dict[int, list[dict]] = defaultdict(list)
        by_t: dict[str, list[dict]] = defaultdict(list)
        for x in ps:
            by_a[x["artist_id"]].append(x)
            by_t[x["track_id"]].append(x)
        a_ranked = sorted(by_a.items(), key=lambda kv: (-len(kv[1]), -sum(i["ms_imputed"] for i in kv[1]), kv[0]))
        for rk, (aid, items) in enumerate(a_ranked, 1):
            mart_artist_year_all.append(
                {
                    "year": y,
                    "artist_id": aid,
                    "plays": len(items),
                    "listen_hours": sum(i["ms_imputed"] for i in items) / 3.6e6,
                    "rank": rk,
                }
            )
        t_ranked = sorted(by_t.items(), key=lambda kv: (-len(kv[1]), -sum(i["ms_imputed"] for i in kv[1]), kv[0]))
        for rk, (tid, items) in enumerate(t_ranked, 1):
            mart_track_year_all.append(
                {
                    "year": y,
                    "track_id": tid,
                    "artist_id": items[0]["artist_id"],
                    "plays": len(items),
                    "listen_hours": sum(i["ms_imputed"] for i in items) / 3.6e6,
                    "rank": rk,
                }
            )

    mart_artist_year = [r for r in mart_artist_year_all if r["rank"] <= 50]
    mart_track_year = [r for r in mart_track_year_all if r["rank"] <= 50]

    # --- Mart 4: clock.json ---
    clock_counts = Counter((p["year"], p["weekday"], p["hour"]) for p in plays_list)
    mart_clock = [
        {"year": y, "weekday": w, "hour": h, "plays": n} for (y, w, h), n in sorted(clock_counts.items())
    ]

    # --- Mart 5: genre_year.json ---
    genre_counts: dict[tuple[int, str, str], float] = defaultdict(float)
    for p in plays_list:
        st = A[p["artist_id"]].genre
        pg = parent_map[st]
        genre_counts[(p["year"], pg, st)] += 1.0
    mart_genre_year = [
        {"year": y, "parent_genre": pg, "style": st, "plays_weighted": w}
        for (y, pg, st), w in sorted(genre_counts.items())
    ]

    # --- Mart 6: platform_year.json ---
    plat_counts = Counter((p["year"], p["platform_family"] or "unknown") for p in plays_list)
    mart_platform_year = [
        {"year": y, "platform_family": pf, "plays": n} for (y, pf), n in sorted(plat_counts.items())
    ]

    # --- Mart 7: artist_arc.json ---
    by_artist_year: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for p in plays_list:
        by_artist_year[p["artist_id"]][p["year"]] += 1
    mart_artist_arc = []
    for aid in sorted(by_artist_year):
        ymap = by_artist_year[aid]
        ys = sorted(ymap)
        tot = sum(ymap.values())
        gaps = [0] + [ys[i] - ys[i - 1] - 1 for i in range(1, len(ys))]
        comebacks = [ys[i] for i, gp in enumerate(gaps) if gp >= 3]
        peak_y = min(ys, key=lambda y: (-ymap[y], y))
        mart_artist_arc.append(
            {
                "artist_id": aid,
                "plays": tot,
                "first_year": ys[0],
                "last_year": ys[-1],
                "years_active": len(ys),
                "longest_gap_years": max(gaps),
                "comeback_year": min(comebacks) if comebacks else None,
                "peak_year": peak_y,
                "peak_share": ymap[peak_y] / tot,
            }
        )

    # --- Mart 8: binge.json & earworm_halflife.json ---
    by_track_days: dict[str, list[dt.date]] = defaultdict(list)
    for p in plays_list:
        by_track_days[p["track_id"]].append(p["date"])

    mart_binge_all = []
    mart_earworm = []
    for tid in sorted(by_track_days):
        days = sorted(by_track_days[tid])
        if len(days) < 10:
            continue
        lifetime = len(days)
        span_days = max(14, (days[-1] - days[0]).days + 1)
        day_counts = Counter(days)
        unique_days = sorted(day_counts)
        best_start = unique_days[0]
        best_plays = 0
        for d0 in unique_days:
            d_end = d0 + timedelta(days=14)
            w_plays = sum(c for d1, c in day_counts.items() if d0 <= d1 < d_end)
            if w_plays > best_plays or (w_plays == best_plays and d0 < best_start):
                best_plays = w_plays
                best_start = d0
        rate_ratio = best_plays / (lifetime * 14.0 / span_days)
        row_b = {
            "track_id": tid,
            "window_start": best_start.isoformat(),
            "window_plays": best_plays,
            "lifetime_plays": lifetime,
            "rate_ratio": rate_ratio,
        }
        mart_binge_all.append(row_b)
        if best_plays >= 15:
            w_end = best_start + timedelta(days=14)
            w_30 = best_start + timedelta(days=44)
            w_365 = best_start + timedelta(days=379)
            pre = sum(1 for d1 in days if d1 < best_start)
            p30 = sum(1 for d1 in days if w_end <= d1 < w_30)
            p365 = sum(1 for d1 in days if w_end <= d1 < w_365)
            later = sum(1 for d1 in days if d1 >= w_end)
            arch = (
                "Flash Burnout"
                if later <= best_plays * 0.35
                else ("Canonized Anthem" if later >= best_plays * 1.25 else "Steady Rotation")
            )
            mart_earworm.append(
                {
                    "track_id": tid,
                    "window_start": best_start.isoformat(),
                    "window_plays": best_plays,
                    "lifetime_plays": lifetime,
                    "rate_ratio": round(rate_ratio, 2),
                    "pre_plays": pre,
                    "post_30d_plays": p30,
                    "post_365d_plays": p365,
                    "later_plays": later,
                    "post_survival_share": round(later / lifetime, 4),
                    "archetype": arch,
                }
            )

    mart_binge = [r for r in mart_binge_all if r["window_plays"] >= 15]

    # --- Mart 9: remixer_year.json ---
    remixer_id = g.special["remixer"]
    remix_isrcs = {R[rid].isrc for rid in g.special["remix_recs"]}
    remix_work_keys = {(R[rid].artist, R[rid].base_norm) for rid in g.special["remix_recs"]}
    orig_isrcs = {
        rec.isrc
        for rec in R.values()
        if (rec.artist, rec.base_norm) in remix_work_keys and not (bool(rec.mix_norm) and not rec.generic_mix)
    }
    rx_by_y = Counter(p["year"] for p in plays_list if p["track_id"] in remix_isrcs)
    or_by_y = Counter(p["year"] for p in plays_list if p["track_id"] in orig_isrcs)
    mart_remixer_year = []
    for y in sorted(set(rx_by_y) | set(or_by_y)):
        if rx_by_y[y] > 0 or or_by_y[y] > 0:
            mart_remixer_year.append(
                {
                    "artist_id": remixer_id,
                    "year": y,
                    "remix_plays": rx_by_y[y],
                    "original_plays": or_by_y[y],
                }
            )

    # --- Mart 10: song_age.json ---
    age_counts = Counter()
    for p in plays_list:
        rec = p["rec"]
        wy = work_year_map.get((rec.artist, rec.base_norm))
        if wy is None:
            b = "unknown"
        else:
            ag = p["year"] - wy
            b = "0" if ag <= 0 else "1-2" if ag <= 2 else "3-5" if ag <= 5 else "6-10" if ag <= 10 else "11-20" if ag <= 20 else "21+"
        age_counts[(p["year"], b)] += 1
    mart_song_age = [{"year": y, "age_bucket": b, "plays": n} for (y, b), n in sorted(age_counts.items())]

    # --- Mart 11: skip_rate.json ---
    sp_plays_by_y = Counter(p["year"] for p in plays_list if p["source"] != "lastfm")
    mart_skip_rate = []
    for y in sorted(sp_plays_by_y):
        if y >= 2012:
            sk = skips_by_y[y]
            sp_n = sp_plays_by_y[y]
            mart_skip_rate.append(
                {"year": y, "skips": sk, "spotify_plays": sp_n, "skip_rate": sk / (sk + sp_n)}
            )

    # --- Mart 12: sessions_year.json ---
    sess_durs_by_y: dict[int, list[float]] = defaultdict(list)
    for es in sess.values():
        y = es[0]["local"].year
        dur_min = (max(e["end"] for e in es) - es[0]["start"]).total_seconds() / 60.0
        sess_durs_by_y[y].append(dur_min)
    s10_by_y = Counter()
    s30_by_y = Counter()
    for x in plays_list + skips_list:
        if x["new_session_10"]:
            s10_by_y[x["year"]] += 1
        if x["new_session_30"]:
            s30_by_y[x["year"]] += 1
    mart_sessions_year = []
    for y in sorted(sess_durs_by_y):
        durs = sess_durs_by_y[y]
        mart_sessions_year.append(
            {
                "year": y,
                "sessions": len(durs),
                "median_minutes": float(statistics.median(durs)),
                "p90_minutes": quantile_cont(durs, 0.9),
                "sessions_10": s10_by_y[y],
                "sessions_30": s30_by_y[y],
            }
        )

    # --- Mart 13: country_year.json ---
    ctry_plays = Counter((p["year"], p["country"] or "unknown") for p in plays_list)
    ctry_imp = Counter((p["year"], p["country"] or "unknown") for p in plays_list if p["country_imputed"])
    mart_country_year = [
        {"year": y, "country": c, "plays": n, "imputed_plays": ctry_imp[(y, c)]}
        for (y, c), n in sorted(ctry_plays.items())
    ]

    # --- Mart 14 & 15: track_label.json & artist_label.json ---
    rec_by_isrc = {rec.isrc: rec for rec in R.values()}
    keep_tids = {r["track_id"] for r in mart_track_year} | {
        r["track_id"] for r in mart_binge_all if r["rate_ratio"] >= 3
    }
    mart_track_label = [
        {"track_id": tid, "title": rec_by_isrc[tid].spotify_title(A), "artist_id": rec_by_isrc[tid].artist}
        for tid in sorted(keep_tids)
        if tid in rec_by_isrc
    ]
    keep_aids = (
        {r["artist_id"] for r in mart_artist_year}
        | {r["artist_id"] for r in mart_track_year}
        | {r["artist_id"] for r in mart_artist_arc if r["plays"] >= 50}
        | {r["artist_id"] for r in mart_remixer_year}
        | {r["artist_id"] for r in mart_track_label}
        | set(A.keys())
    )
    mart_artist_label = [{"artist_id": aid, "name": A[aid].name} for aid in sorted(keep_aids) if aid in A]

    # --- Insight Marts (50_insights.sql) ---
    # 1. obscurity_year
    obs_groups: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for p in plays_list:
        lst = A[p["artist_id"]].listeners
        tier = (
            "Deep Underground (<25k)"
            if lst < 25_000
            else "Indie & Niche (25k–150k)"
            if lst < 150_000
            else "Mid-Tier (150k–750k)"
            if lst < 750_000
            else "Global Mainstream (750k+)"
        )
        obs_groups[(p["year"], tier)].append(p)
    mart_obscurity_year = [
        {
            "year": y,
            "tier": t,
            "plays": len(items),
            "listen_hours": round(sum(i["ms_imputed"] for i in items) / 3.6e6, 2),
            "artists": len({i["artist_id"] for i in items}),
        }
        for (y, t), items in sorted(obs_groups.items())
    ]

    # 2. vanguard
    mart_vanguard = []
    for arc_row in mart_artist_arc:
        if arc_row["plays"] < 15:
            continue
        a = A[arc_row["artist_id"]]
        mart_vanguard.append(
            {
                "artist_id": a.aid,
                "name": a.name,
                "begin_year": a.begin_year,
                "first_play_year": arc_row["first_year"],
                "discovery_lag_years": arc_row["first_year"] - a.begin_year,
                "plays": arc_row["plays"],
                "years_active": arc_row["years_active"],
                "lastfm_listeners": a.listeners,
                "country": a.country or "unknown",
            }
        )
    mart_vanguard.sort(key=lambda x: (x["discovery_lag_years"], -x["plays"], x["artist_id"]))

    # 3. intent_skip
    intent_groups: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for x in plays_list + skips_list:
        if x["source"] == "lastfm" or x["year"] < 2011:
            continue
        mode = (
            "Shuffle Autopilot"
            if x["shuffle"]
            else ("Hand-Picked (Click/Play)" if x["reason_start"] in ("clickrow", "playbtn") else "Album / Queue Flow")
        )
        intent_groups[(x["year"], mode)].append(x)
    mart_intent_skip = []
    for (y, mode), items in sorted(intent_groups.items()):
        pl_items = [i for i in items if not i["is_skip"]]
        sk_items = [i for i in items if i["is_skip"]]
        ratios_valid = [i["completion_ratio"] for i in pl_items if i["completion_ratio"] is not None]
        mart_intent_skip.append(
            {
                "year": y,
                "intent_mode": mode,
                "plays": len(pl_items),
                "skips": len(sk_items),
                "skip_under_5s": sum(1 for i in sk_items if (i["ms_played"] or 0) < 5000),
                "skip_5_to_15s": sum(1 for i in sk_items if 5000 <= (i["ms_played"] or 0) < 15000),
                "skip_15_to_30s": sum(1 for i in sk_items if (i["ms_played"] or 0) >= 15000),
                "avg_completion": round(statistics.mean(ratios_valid), 4) if ratios_valid else 0.95,
            }
        )

    # 4. tempo_pulse
    by_hr: dict[int, list[tuple[float, float]]] = defaultdict(list)
    by_sidx: dict[int, list[tuple[float, float]]] = defaultdict(list)
    by_yr: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for p in plays_list:
        if p["track_id"] in dz_map:
            bpm_g = dz_map[p["track_id"]]
            by_hr[p["hour"]].append(bpm_g)
            by_sidx[min(p["session_index"], 15)].append(bpm_g)
            by_yr[p["year"]].append(bpm_g)

    mart_tempo_pulse = []
    for btype, bmap in (("hour", by_hr), ("session_index", by_sidx), ("year", by_yr)):
        for b in sorted(bmap):
            vals = bmap[b]
            bpms = [v[0] for v in vals]
            gains = [v[1] for v in vals]
            mart_tempo_pulse.append(
                {
                    "bucket_type": btype,
                    "bucket": b,
                    "plays": len(vals),
                    "avg_bpm": round(statistics.mean(bpms), 2),
                    "p25_bpm": round(quantile_cont(bpms, 0.25), 2),
                    "p75_bpm": round(quantile_cont(bpms, 0.75), 2),
                    "avg_gain": round(statistics.mean(gains), 2),
                }
            )

    # 5. artist_passport
    pass_groups: dict[tuple[int, str, str], list[int]] = defaultdict(list)
    for p in plays_list:
        lc = p["country"] or "unknown"
        ac = A[p["artist_id"]].country or "unknown"
        pass_groups[(p["year"], lc, ac)].append(p["artist_id"])
    mart_artist_passport = [
        {
            "year": y,
            "listener_country": lc,
            "artist_country": ac,
            "plays": len(aids),
            "artists": len(set(aids)),
        }
        for (y, lc, ac), aids in sorted(pass_groups.items())
    ]

    # 6. explorer_events
    explorer_events = []
    for x in plays_list + skips_list:
        rec = x["rec"]
        a = A[x["artist_id"]]
        alb = AL[x["album_id"]] if x["album_id"] in AL else None
        st = a.genre
        pg = parent_map[st]
        explorer_events.append(
            {
                "ts": x["started_at_local"].isoformat(),
                "artist": a.name,
                "title": rec.spotify_title(A),
                "album": alb.name if alb else None,
                "artist_norm": a.norm,
                "title_norm": rec.full_norm,
                "parent_genre": pg,
                "style": st,
                "minutes": round(x["ms_imputed"] / 60000.0, 2),
                "is_skip": x["is_skip"],
                "platform": x["platform_family"],
                "country": x["country"],
                "source": x["source"],
            }
        )
    explorer_events.sort(key=lambda r: (r["artist"], r["album"] or "", r["title"], r["ts"]))

    outputs = {
        "year": mart_year,
        "artist_year": mart_artist_year,
        "track_year": mart_track_year,
        "clock": mart_clock,
        "genre_year": mart_genre_year,
        "platform_year": mart_platform_year,
        "artist_arc": mart_artist_arc,
        "binge": mart_binge,
        "remixer_year": mart_remixer_year,
        "song_age": mart_song_age,
        "skip_rate": mart_skip_rate,
        "sessions_year": mart_sessions_year,
        "country_year": mart_country_year,
        "artist_label": mart_artist_label,
        "track_label": mart_track_label,
        "obscurity_year": mart_obscurity_year,
        "vanguard": mart_vanguard,
        "earworm_halflife": mart_earworm,
        "intent_skip": mart_intent_skip,
        "tempo_pulse": mart_tempo_pulse,
        "artist_passport": mart_artist_passport,
        "explorer_events": explorer_events,
    }

    for name, rows in outputs.items():
        (CACHE_DIR / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False))
    marker.write_text(json.dumps({"status": "ok", "marts": list(outputs.keys())}))


if __name__ == "__main__":
    build_all_marts()
    if len(sys.argv) == 2 and sys.argv[1] != "--build-only":
        target = CACHE_DIR / f"{sys.argv[1]}.json"
        if target.exists():
            sys.stdout.write(target.read_text())
            sys.exit(0)
    elif len(sys.argv) == 3 and sys.argv[1] == "--parquet":
        # Emit explorer_events JSON bytes when DuckDB Parquet export is unavailable in stdlib python
        target = CACHE_DIR / "explorer_events.json"
        sys.stdout.buffer.write(target.read_bytes())
        sys.exit(0)
