"""Build the seeded scenario fixture (W0).

Writes, relative to the current checkout (so every git worktree gets its own):
  fixtures/raw/Streaming_History_Audio_<year>.json   fake Spotify export
  fixtures/raw/Streaming_History_Video_2024.json     a few video rows
  fixtures/raw/recenttracks-fixture.csv               fake Last.fm export
  dev_fixtures.duckdb                                 every schema.sql table, filled
                                                      with the EXPECTED pipeline output,
                                                      plus truth_* and fixture_scenarios

The history is simulated from a ground truth of listens (2007-04 to 2026-10),
then observed through Spotify and Last.fm the way the real exports behave:
Last.fm-only before Jul 2011, sparse scrobbling 2014-2019, near-complete overlap
from 2022, double scrobbles, scrobble drift, skips, pauses, two-device overlaps,
a ZZ country block, trips abroad and DST edges. Named scenarios (binge,
comeback, staple, remixer, remaster, multi-URI, longform) are recorded in
fixture_scenarios so mart tests can assert on them.

Deterministic: the same SEED always produces byte-identical outputs.
Usage: uv run python scripts/make_fixtures.py [--out DIR]
  --out DIR writes DIR/raw/ and DIR/dev_fixtures.duckdb instead (used by the determinism test).
"""

from __future__ import annotations

import csv
import json
import math
import random
import statistics
import string
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import config
from pipeline.config import COUNTRY_TZ_CSV, SCHEMA_SQL

FIXTURE_DB, FIXTURE_RAW_DIR = config.FIXTURE_DB, config.FIXTURE_RAW_DIR

SEED = 20260422
START = date(2007, 4, 1)
END = date(2026, 10, 20)
SPOTIFY_FROM = date(2011, 7, 1)
LASTFM_ONLY_ID_OFFSET = 1_000_000_000_000

GENRES = ["indie rock", "electro house", "dubstep", "hip hop", "k-pop", "house", "techno", "v-pop", "j-pop", "ambient"]
ERAS = [  # (first year, last year, genre weights)
    (2007, 2010, {"indie rock": 45, "electro house": 20, "hip hop": 15, "j-pop": 10, "ambient": 10}),
    (2011, 2014, {"electro house": 35, "dubstep": 25, "indie rock": 15, "hip hop": 10, "k-pop": 15}),
    (2015, 2019, {"k-pop": 35, "house": 20, "hip hop": 15, "indie rock": 10, "v-pop": 10, "ambient": 10}),
    (2020, 2026, {"techno": 30, "house": 30, "k-pop": 10, "v-pop": 10, "ambient": 10, "hip hop": 10}),
]
GENRE_BPM = {"indie rock": 120, "electro house": 128, "dubstep": 140, "hip hop": 92, "k-pop": 118,
             "house": 124, "techno": 132, "v-pop": 100, "j-pop": 130, "ambient": 80}
SCROBBLE_COVERAGE = {2011: 0.85, 2012: 0.85, 2013: 0.85, 2014: 0.02, 2015: 0.15, 2016: 0.15, 2017: 0.15,
                     2018: 0.02, 2019: 0.2, 2020: 0.6, 2021: 0.6}  # pre-2011 = 1.0, 2022+ = 0.97
PLATFORMS = {
    "windows": "Windows 7 (Unknown Ed) SP1 [x86 0]",
    "android": "Android OS 8.0.0 API 26 (samsung, SM-G950U)",
    "web": "WebPlayer (websocket RFC6455)",
    "ios": "ios",
    "cast": "Partner google cast_tv",
    "mac": "OS X 10.13.6 [x86 8]",
}
TRIPS = [  # (country, first day, last day)
    ("JP", date(2023, 4, 1), date(2023, 4, 10)),
    ("FR", date(2024, 6, 10), date(2024, 6, 17)),
    ("CA", date(2025, 2, 14), date(2025, 2, 18)),
    ("VN", date(2019, 12, 20), date(2020, 1, 5)),  # inside the ZZ block: unrecoverable
]
ZZ_BLOCK = (date(2016, 3, 1), date(2020, 8, 31))
BINGE_WINDOW = (date(2019, 5, 1), date(2019, 5, 12))
DST_DAYS = [date(2024, 3, 10), date(2024, 11, 3)]

WORDS_A = ["night", "glass", "paper", "silver", "neon", "velvet", "hollow", "golden", "electric", "quiet",
           "violet", "broken", "summer", "winter", "ocean", "static", "crystal", "midnight", "hidden", "wild"]
WORDS_B = ["signal", "harbor", "lanterns", "garden", "machine", "river", "echo", "parade", "satellite", "mirror",
           "engine", "season", "frequency", "horizon", "letters", "circuit", "fever", "bloom", "tide", "motion"]
NAME_A = ["Kilo", "Mara", "Ivo", "Sable", "Juno", "Tove", "Rook", "Nico", "Ada", "Lumen", "Oslo", "Pax",
          "Vesper", "Wren", "Zephyr", "Cato", "Esme", "Faro", "Gale", "Hux"]
NAME_B = ["Vantage", "Static", "Ferro", "Bloom", "Atlas", "Rivers", "Hale", "North", "Quill", "Drift",
          "Ember", "Lyric", "Morrow", "Pine", "Shore", "Tide", "Vale", "Wilder", "Yards", "Zero"]
SPECIAL_ARTISTS = [  # (display, Last.fm spelling, norm, genre)
    ("Lâm Đức Phương", "Lam Duc Phuong", "lam duc phuong", "v-pop"),
    ("Hoàng Thùy Mai", "Hoàng Thùy Mai", "hoang thuy mai", "v-pop"),
    ("夜空ノート", "夜空ノート", "夜空ノート", "j-pop"),
    ("별빛소녀", "별빛소녀", "별빛소녀", "k-pop"),
    ("Beyoncé Fixture", "Beyonce Fixture", "beyonce fixture", "hip hop"),
]


@dataclass
class Artist:
    aid: int
    name: str
    lfm_name: str
    norm: str
    genre: str
    mbid: str | None
    spotify_id: str
    listeners: int
    country: str | None
    begin_year: int


@dataclass
class Album:
    album_id: int
    name: str
    norm: str
    artist: int
    album_type: str
    release_date: str
    spotify_id: str
    mbid: str | None


@dataclass
class Recording:
    rid: int
    artist: int
    base_title: str
    base_norm: str
    mix_title: str | None  # display, e.g. "Kilo Vantage Remix"
    mix_norm: str | None
    generic_mix: bool
    remixer: int | None
    featured: int | None
    remaster_of: int | None
    isrc: str
    duration_ms: int
    recording_year: int
    mbid: str | None
    uris: list[tuple[str, int]] = field(default_factory=list)  # (uri, album_id)

    @property
    def full_norm(self) -> str:
        return f"{self.base_norm} ({self.mix_norm})" if self.mix_norm else self.base_norm

    def spotify_title(self, artists: dict[int, Artist]) -> str:
        t = self.base_title
        if self.remaster_of is not None:
            t += f" - {self.recording_year} Remaster"
        if self.mix_title:
            t += f" - {self.mix_title}"
        if self.featured is not None:
            t += f" (feat. {artists[self.featured].name})"
        return t


@dataclass
class Listen:
    rec: Recording
    uri: str | None
    true_start: datetime  # UTC
    ms_played: int
    pause_s: float
    country: str  # true country
    platform: str | None
    shuffle: bool
    skipped: bool
    reason_start: str
    reason_end: str
    offline: bool
    incognito: bool
    on_spotify: bool
    scrobble_t: datetime | None = None
    lfm_title: str | None = None
    lfm_artist: str | None = None
    lfm_variant: str = "same"  # same|pass2
    dupe_t: datetime | None = None


class Gen:
    def __init__(self) -> None:
        self.r = random.Random(SEED)
        self.artists: dict[int, Artist] = {}
        self.albums: dict[int, Album] = {}
        self.recs: dict[int, Recording] = {}
        self.by_genre: dict[str, list[int]] = defaultdict(list)
        self.recs_by_artist: dict[int, list[int]] = defaultdict(list)
        self.scenarios: list[tuple[str, str, str]] = []
        self.isrc_n = 0

    # ---- ids ---------------------------------------------------------------
    def b62(self, n: int) -> str:
        return "".join(self.r.choice(string.ascii_letters + string.digits) for _ in range(n))

    def mbid(self, p: float) -> str | None:
        return str(uuid.UUID(int=self.r.getrandbits(128), version=4)) if self.r.random() < p else None

    def isrc(self, year: int) -> str:
        self.isrc_n += 1
        return f"QZFX{year % 100:02d}{self.isrc_n:05d}"

    # ---- catalog -------------------------------------------------------------
    def add_artist(self, name: str, lfm_name: str, norm: str, genre: str, pooled: bool = True) -> Artist:
        aid = len(self.artists) + 1
        a = Artist(aid, name, lfm_name, norm, genre, self.mbid(0.7), self.b62(22),
                   int(5_000 * (600 ** self.r.random())), self.r.choice(["US", "GB", "DE", "KR", "JP", "VN", None]),
                   self.r.randint(1995, 2018))
        self.artists[aid] = a
        if pooled:  # scenario artists are only played by their scenario rule
            self.by_genre[genre].append(aid)
        return a

    def add_album(self, artist: int, name: str, album_type: str, year: int) -> Album:
        alb = Album(len(self.albums) + 1, name, name.lower(), artist, album_type,
                    f"{year}-{self.r.randint(1, 12):02d}-{self.r.randint(1, 28):02d}", self.b62(22), self.mbid(0.6))
        self.albums[alb.album_id] = alb
        return alb

    def add_rec(self, artist: int, title: str, year: int, album: Album, *, mix: str | None = None,
                generic: bool = False, remixer: int | None = None, featured: int | None = None,
                remaster_of: int | None = None, duration_ms: int | None = None) -> Recording:
        rec = Recording(len(self.recs) + 1, artist, title, title.lower(), mix, mix.lower() if mix else None,
                        generic, remixer, featured, remaster_of, self.isrc(year),
                        duration_ms or self.r.randint(150_000, 330_000), year, self.mbid(0.6))
        rec.uris.append((f"spotify:track:{self.b62(22)}", album.album_id))
        self.recs[rec.rid] = rec
        self.recs_by_artist[artist].append(rec.rid)
        return rec

    def title(self, used: set[str]) -> str:
        while True:
            t = f"{self.r.choice(WORDS_A).title()} {self.r.choice(WORDS_B).title()}"
            if t not in used:
                used.add(t)
                return t

    def build_catalog(self) -> None:
        r = self.r
        used_names: set[str] = {"Oslo Wilder", "Pax Ember", "Mara Lantern"}  # scenario artists
        for genre in GENRES:
            for _ in range(7):
                while True:
                    n = f"{r.choice(NAME_A)} {r.choice(NAME_B)}"
                    if n not in used_names:
                        used_names.add(n)
                        break
                self.add_artist(n, n, n.lower(), genre)
        for disp, lfm, norm, genre in SPECIAL_ARTISTS:
            self.add_artist(disp, lfm, norm, genre)

        titles: dict[int, set[str]] = defaultdict(set)
        for aid, a in list(self.artists.items()):
            year = r.randint(2004, 2025)
            alb = self.add_album(aid, f"{self.title(set())} LP", "album", year)
            for _ in range(r.randint(4, 8)):
                feat = r.choice(self.by_genre[a.genre]) if r.random() < 0.12 else None
                self.add_rec(aid, self.title(titles[aid]), year, alb, featured=feat if feat != aid else None)
            # some extended mixes for dance genres
            if a.genre in ("electro house", "house", "techno", "dubstep"):
                orig = self.recs[self.recs_by_artist[aid][0]]
                self.add_rec(aid, orig.base_title, year, alb, mix="Extended Mix", generic=True,
                             duration_ms=orig.duration_ms + 120_000)
            # a few multi-URI recordings: same ISRC on a single
            if r.random() < 0.25:
                rec = self.recs[self.recs_by_artist[aid][1]]
                single = self.add_album(aid, rec.base_title, "single", rec.recording_year)
                rec.uris.append((f"spotify:track:{self.b62(22)}", single.album_id))

        # --- named scenario artists ------------------------------------------
        staple = self.add_artist("Mara Lantern", "Mara Lantern", "mara lantern", "indie rock", pooled=False)
        alb08 = self.add_album(staple.aid, "Harbor Lights", "album", 2008)
        glass = self.add_rec(staple.aid, "Glass Harbor", 2008, alb08)
        paper = self.add_rec(staple.aid, "Paper Lanterns", 2008, alb08)
        for _ in range(4):
            self.add_rec(staple.aid, self.title(titles[staple.aid]), 2008, alb08)
        single09 = self.add_album(staple.aid, "Glass Harbor", "single", 2009)
        comp24 = self.add_album(staple.aid, "Fixture Hits 2024", "compilation", 2024)
        glass.uris += [(f"spotify:track:{self.b62(22)}", single09.album_id),
                       (f"spotify:track:{self.b62(22)}", comp24.album_id)]
        alb21 = self.add_album(staple.aid, "Harbor Lights (Remastered)", "album", 2021)
        remaster = self.add_rec(staple.aid, "Paper Lanterns", 2021, alb21, remaster_of=paper.rid,
                                duration_ms=paper.duration_ms + 1_000)
        comeback = self.add_artist("Oslo Wilder", "Oslo Wilder", "oslo wilder", "indie rock", pooled=False)
        cb_alb = self.add_album(comeback.aid, "Return Address", "album", 2008)
        for _ in range(6):
            self.add_rec(comeback.aid, self.title(titles[comeback.aid]), 2008, cb_alb)
        flash = self.add_artist("Pax Ember", "Pax Ember", "pax ember", "dubstep", pooled=False)
        fl_alb = self.add_album(flash.aid, "Flashpoint", "album", 2013)
        for _ in range(5):
            self.add_rec(flash.aid, self.title(titles[flash.aid]), 2013, fl_alb)
        binge_artist = self.by_genre["k-pop"][0]
        binge = self.recs[self.recs_by_artist[binge_artist][0]]
        remixer = self.add_artist("Kilo Vantage Fixture", "Kilo Vantage Fixture", "kilo vantage fixture", "house", pooled=False)
        rx_alb = self.add_album(remixer.aid, "Remixes", "compilation", 2019)
        remix_recs = []
        for host in self.by_genre["house"][:3] + self.by_genre["techno"][:3]:
            orig = self.recs[self.recs_by_artist[host][3]]  # a deep cut, so the remix outplays it
            rx = self.add_rec(host, orig.base_title, 2019, rx_alb, mix="Kilo Vantage Fixture Remix", remixer=remixer.aid)
            remix_recs.append(rx.rid)
        djmix = self.add_rec(remixer.aid, "Live Set at Fixture Hall", 2021, rx_alb, mix="DJ Mix",
                             duration_ms=3_720_000)
        long_artist = self.by_genre["ambient"][0]
        longtrack = self.add_rec(long_artist, "Long Distance", 2015,
                                 self.albums[self.recs[self.recs_by_artist[long_artist][0]].uris[0][1]],
                                 duration_ms=840_000)
        for rid in remix_recs + [longtrack.rid]:  # only reachable through their scenario rule
            self.recs_by_artist[self.recs[rid].artist].remove(rid)
        self.special = {"staple": staple.aid, "comeback": comeback.aid, "flash": flash.aid, "binge": binge.rid,
                            "remixer": remixer.aid, "remix_recs": remix_recs, "djmix": djmix.rid, "longtrack": longtrack.rid,
                            "glass": glass.rid, "paper": paper.rid, "remaster": remaster.rid}
        self.scenarios += [
            ("staple", "artist_norm", staple.norm),
            ("staple", "rule", "played in every year 2007-2026"),
            ("comeback", "artist_norm", comeback.norm),
            ("comeback", "rule", "played 2008-2011, silent 2012-2015, back 2016-2026"),
            ("flash", "artist_norm", flash.norm),
            ("flash", "rule", "heavy in 2013 only"),
            ("binge", "track_id", binge.isrc),
            ("binge", "rule", f">= 24 plays between {BINGE_WINDOW[0]} and {BINGE_WINDOW[1]}"),
            ("remixer", "artist_norm", remixer.norm),
            ("remixer", "rule", "6 remixes of house/techno tracks, played 2018-2026 more than their originals"),
            ("multi_uri", "track_id", glass.isrc),
            ("multi_uri", "rule", "one ISRC on album 2008, single 2009, compilation 2024: recording_year 2008"),
            ("remaster", "track_id_original", paper.isrc),
            ("remaster", "track_id_remaster", remaster.isrc),
            ("remaster", "rule", "same work_id; remaster recording_year 2021, work_year 2008"),
            ("longform", "track_id", djmix.isrc),
            ("longform", "rule", "62 min DJ mix played 15-20 min: is_longform_mix, no completion_ratio"),
            ("long_track", "track_id", longtrack.isrc),
            ("long_track", "rule", "14 min track without mix keyword: NOT longform"),
            ("zz_block", "rule", f"conn_country ZZ from {ZZ_BLOCK[0]} to {ZZ_BLOCK[1]}: country NULL, tz LA"),
            ("travel", "rule", "JP 2023-04-01..10, FR 2024-06-10..17, CA 2025-02-14..18 (multi-zone)"),
            ("vn_trip", "rule", "VN 2019-12-20..2020-01-05 falls inside the ZZ block, so it is not recoverable"),
            ("dst", "rule", "sessions across 2024-03-10 and 2024-11-03 01:00-03:30 local"),
            ("eras", "rule", json.dumps({f"{a}-{b}": w for a, b, w in ERAS})),
        ]

    # ---- simulation -------------------------------------------------------------
    def country_on(self, d: date) -> str:
        for c, a, b in TRIPS:
            if a <= d <= b:
                return c
        return "US"

    def era(self, y: int) -> dict[str, int]:
        return next(w for a, b, w in ERAS if a <= y <= b)

    def pick(self, d: date, prev: Recording | None) -> Recording:
        r, y, sp = self.r, d.year, self.special
        if prev is not None and r.random() < 0.2:
            return self.recs[r.choice(self.recs_by_artist[prev.artist])]
        roll = r.random()
        if roll < 0.03:
            return self.recs[r.choice(self.recs_by_artist[sp["staple"]])]
        if roll < 0.05 and (2008 <= y <= 2011 or y >= 2016):
            return self.recs[r.choice(self.recs_by_artist[sp["comeback"]])]
        if roll < 0.13 and y == 2013:
            return self.recs[r.choice(self.recs_by_artist[sp["flash"]])]
        if roll < 0.16 and y >= 2018:
            return self.recs[r.choice(sp["remix_recs"])]
        if roll < 0.163 and 2021 <= y <= 2024:
            return self.recs[sp["djmix"]]
        if roll < 0.166 and y >= 2015:
            return self.recs[sp["longtrack"]]
        w = self.era(y)
        genre = r.choices(list(w), weights=list(w.values()))[0]
        pool = self.by_genre[genre]
        aid = pool[min(int(r.paretovariate(1.2)) - 1, len(pool) - 1)]
        recs = self.recs_by_artist[aid]
        return self.recs[recs[min(int(r.paretovariate(1.0)) - 1, len(recs) - 1)]]

    def platform(self, y: int) -> str:
        if y <= 2013:
            fam = self.r.choices(["windows", "android"], [7, 3])[0]
        elif y <= 2019:
            fam = self.r.choices(["android", "windows", "web"], [7, 2, 1])[0]
        else:
            fam = self.r.choices(["ios", "cast", "mac"], [6, 2.5, 1.5])[0]
        return fam

    def session_hour(self, y: int) -> float:
        r = self.r
        if y <= 2011:
            return r.gauss(21, 2)
        if y <= 2016:
            return r.choice([r.gauss(10, 1.5), r.gauss(15, 1.5), r.gauss(21, 2)])
        return r.choice([r.gauss(8, 1), r.gauss(18, 1), r.gauss(22, 1.5)])

    def simulate(self) -> list[Listen]:
        r = self.r
        out: list[Listen] = []
        d = START
        while d <= END:
            y = d.year
            n_sessions = poisson(r, 1.0 if y < 2011 else 1.3)
            extra: list[tuple[float, list[Recording] | None]] = [(self.session_hour(y), None) for _ in range(n_sessions)]
            if BINGE_WINDOW[0] <= d <= BINGE_WINDOW[1]:
                extra.append((12.5, [self.recs[self.special["binge"]]] * 2))
            if d in DST_DAYS:
                extra.append((1.0, None))
            if d.month == 7 and d.day == 4 and y >= 2012:
                extra.append((14.0, None))  # guaranteed long-gap structure for sessions
            for hour, forced in extra:
                out += self.session(d, hour, forced)
            d += timedelta(days=1)
        out.sort(key=lambda x: x.true_start)
        return out

    def session(self, d: date, hour: float, forced: list[Recording] | None) -> list[Listen]:
        r = self.r
        y = d.year
        country = self.country_on(d)
        tz = ZoneInfo(TZ[country])
        hour = min(max(hour, 0.0), 23.9)
        local = datetime(d.year, d.month, d.day) + timedelta(hours=hour)
        t = local.replace(tzinfo=tz).astimezone(UTC).replace(tzinfo=None)
        on_spotify = d >= SPOTIFY_FROM and not (y <= 2013 and r.random() < 0.3)
        fam = self.platform(y) if on_spotify else None
        shuffle = r.random() < (0.35 if y < 2018 else 0.15)
        n = len(forced) if forced else max(1, int(r.expovariate(1 / 7)))
        listens: list[Listen] = []
        prev: Recording | None = None
        reason_start = r.choice(["clickrow", "appload", "remote", "playbtn", ""])
        for i in range(n):
            rec = forced[i] if forced else self.pick(d, prev)
            dur = rec.duration_ms
            roll = r.random()
            if not on_spotify:
                ms, reason_end, skipped = dur, "trackdone", False
            elif rec.duration_ms > 1_200_000:
                ms, reason_end, skipped = r.randint(900_000, 1_200_000), "endplay", False
            elif roll < 0.25 and not forced:
                ms, reason_end, skipped = r.randint(1_000, 29_000), "fwdbtn", True
            elif roll < 0.35:
                ms, reason_end, skipped = r.randint(30_000, int(dur * 0.9)), "endplay", False
            else:
                ms, reason_end, skipped = dur - r.randint(0, 400), "trackdone", False
            pause = r.uniform(300, 900) if on_spotify and not skipped and r.random() < 0.02 else 0.0
            uri = r.choice(rec.uris)[0] if on_spotify else None
            listens.append(Listen(
                rec, uri, t, ms, pause, country, PLATFORMS[fam] if fam else None,
                shuffle, skipped, reason_start, reason_end,
                on_spotify and r.random() < 0.03, on_spotify and r.random() < 0.005, on_spotify))
            reason_start = "fwdbtn" if skipped else "trackdone"
            prev = rec
            step = ms / 1000 + pause + r.uniform(0, 2)
            if r.random() < 0.01:
                step -= 90  # second device: next play overlaps this one
            t += timedelta(seconds=max(step, 1))
        return listens

    def observe_lastfm(self, listens: list[Listen]) -> None:
        r = self.r
        session_on: dict[tuple[date, int], bool] = {}
        for li in listens:
            y = li.true_start.year
            dur = li.rec.duration_ms
            eligible = dur > 30_000 and li.ms_played >= min(dur / 2, 240_000)
            if not eligible:
                continue
            cov = 1.0 if li.true_start.date() < SPOTIFY_FROM or not li.on_spotify else SCROBBLE_COVERAGE.get(y, 0.97)
            if not li.on_spotify and y >= 2011:
                cov = 0.95
            key = (li.true_start.date(), li.true_start.hour // 6)
            if key not in session_on:
                session_on[key] = r.random() < cov
            if not session_on[key]:
                continue
            roll = r.random()
            if roll < 0.90:
                off = r.gauss(-0.6, 1.2)
            elif roll < 0.98:
                off = r.uniform(20, 85) * r.choice([-1, 1])
            else:
                off = li.ms_played / 1000 + li.pause_s + r.uniform(60, 170)
            li.scrobble_t = li.true_start + timedelta(seconds=off)
            a = self.artists[li.rec.artist]
            li.lfm_artist = a.lfm_name
            if li.rec.featured is not None and r.random() < 0.3:
                li.lfm_artist = f"{a.lfm_name} feat. {self.artists[li.rec.featured].lfm_name}"
            title = li.rec.base_title
            if li.rec.remaster_of is not None and r.random() < 0.5:
                title += f" - {li.rec.recording_year} Remaster"
            if li.rec.mix_title:
                if li.rec.generic_mix and r.random() < 0.3:
                    li.lfm_variant = "pass2"  # player drops 'Extended Mix'
                elif r.random() < 0.4:
                    title += f" ({li.rec.mix_title})"
                else:
                    title += f" - {li.rec.mix_title}"
            li.lfm_title = title
            if y >= 2015 and r.random() < 0.05:
                li.dupe_t = li.scrobble_t + timedelta(seconds=r.uniform(1, 50))


def load_tz() -> dict[str, str]:
    with open(COUNTRY_TZ_CSV, encoding="utf-8") as f:
        return {row["country"]: row["tz"] for row in csv.DictReader(f)}


TZ = load_tz()


def poisson(r: random.Random, lam: float) -> int:
    k, p, limit = 0, 1.0, math.exp(-lam)
    while True:
        p *= r.random()
        if p <= limit:
            return k
        k += 1


def insert(con: duckdb.DuckDBPyConnection, table: str, rows: list) -> None:
    """Bulk insert rows (tuples in table column order) through Arrow; executemany is too slow."""
    if not rows:
        return
    cols = [c[0] for c in con.execute(f"DESCRIBE {table}").fetchall()]
    df = pl.DataFrame(rows, schema=cols, orient="row", strict=False, infer_schema_length=None)
    con.register("_rows", df.to_arrow())
    con.execute(f"INSERT INTO {table} SELECT * FROM _rows")
    con.unregister("_rows")


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    g = Gen()
    g.build_catalog()
    listens = g.simulate()
    g.observe_lastfm(listens)
    r = g.r

    # ---- observed Spotify rows ----------------------------------------------------
    # The export's ts is wall-clock stop time, so a pause pushes ts later and makes
    # ts - ms_played later than the true start.
    zz_extra = set()
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
            zz_extra.add(idx)
        a = g.artists[li.rec.artist]
        alb = g.albums[dict(li.rec.uris)[li.uri]]
        row = {
            "ts": iso(ts), "platform": li.platform, "ms_played": li.ms_played, "conn_country": conn,
            "ip_addr": "203.0.113." + str(r.randint(1, 254)),
            "master_metadata_track_name": li.rec.spotify_title(g.artists),
            "master_metadata_album_artist_name": a.name, "master_metadata_album_album_name": alb.name,
            "spotify_track_uri": li.uri, "episode_name": None, "episode_show_name": None, "spotify_episode_uri": None,
            "audiobook_title": None, "audiobook_uri": None, "audiobook_chapter_uri": None, "audiobook_chapter_title": None,
            "reason_start": li.reason_start, "reason_end": li.reason_end, "shuffle": li.shuffle, "skipped": li.skipped,
            "offline": li.offline, "offline_timestamp": int(ts.timestamp() * 1000) if li.offline else None,
            "incognito_mode": li.incognito}
        sp_rows.append(row)
        sp_of_listen[idx] = row
    # podcasts: no track URI, must not reach stg_spotify
    podcast_rows = []
    for i in range(40):
        ts = datetime(2021, 1, 4, 16, 0) + timedelta(days=7 * i)
        podcast_rows.append(dict(sp_rows[0], ts=iso(ts), ms_played=1_500_000, master_metadata_track_name=None,
                                 master_metadata_album_artist_name=None, master_metadata_album_album_name=None,
                                 spotify_track_uri=None, episode_name=f"Fixture Talk #{i + 1}",
                                 episode_show_name="Fixture Talk", spotify_episode_uri=f"spotify:episode:{g.b62(22)}",
                                 reason_start="clickrow", reason_end="endplay", platform=PLATFORMS["ios"],
                                 conn_country="US", skipped=False, incognito_mode=False))
    video_rows = [dict(sp_rows[-1], ts=iso(datetime(2024, 2, 1 + i, 20, 0)), ms_played=200_000) for i in range(5)]

    # ---- observed Last.fm rows ------------------------------------------------------
    lfm_rows: list[dict] = []
    lfm_of_listen: dict[int, dict] = {}
    dupe_rows: list[dict] = []
    for idx, li in enumerate(listens):
        if li.scrobble_t is None:
            continue
        rec = li.rec
        a = g.artists[rec.artist]
        alb = g.albums[rec.uris[0][1]]
        title = li.lfm_title if li.lfm_variant == "same" else rec.base_title
        base = {"artist": li.lfm_artist, "artist_mbid": a.mbid or "", "album": alb.name, "album_mbid": alb.mbid or "",
                    "track": title, "track_mbid": rec.mbid or ""}
        row = dict(uts=int(li.scrobble_t.replace(tzinfo=UTC).timestamp()), **base)
        lfm_rows.append(row)
        lfm_of_listen[idx] = row
        if li.dupe_t is not None:
            dupe = dict(uts=int(li.dupe_t.replace(tzinfo=UTC).timestamp()), **base)
            lfm_rows.append(dupe)
            dupe_rows.append(dupe)
    for row in lfm_rows:
        row["utc_time"] = datetime.fromtimestamp(row["uts"], UTC).strftime("%d %b %Y, %H:%M")

    write_raw(sp_rows, podcast_rows, video_rows, lfm_rows)
    build_db(g, listens, sp_rows, sp_of_listen, lfm_rows, lfm_of_listen, dupe_rows, podcast_rows, video_rows, zz_extra)


def write_raw(sp_rows, podcast_rows, video_rows, lfm_rows) -> None:
    FIXTURE_RAW_DIR.mkdir(parents=True, exist_ok=True)
    for old in FIXTURE_RAW_DIR.glob("*"):
        old.unlink()
    by_year: dict[int, list[dict]] = defaultdict(list)
    for row in sp_rows + podcast_rows:
        by_year[int(row["ts"][:4])].append(row)
    for y, rows in sorted(by_year.items()):
        rows.sort(key=lambda x: x["ts"])
        (FIXTURE_RAW_DIR / f"Streaming_History_Audio_{y}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    (FIXTURE_RAW_DIR / "Streaming_History_Video_2024.json").write_text(json.dumps(video_rows, ensure_ascii=False))
    cols = ["uts", "utc_time", "artist", "artist_mbid", "album", "album_mbid", "track", "track_mbid"]
    with open(FIXTURE_RAW_DIR / "recenttracks-fixture.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(cols)
        for row in sorted(lfm_rows, key=lambda x: -x["uts"]):  # newest first, like the real export
            w.writerow([str(row[c]) for c in cols])


def platform_family(p: str | None) -> str | None:
    if p is None:
        return None
    for fam, s in PLATFORMS.items():
        if p == s:
            return fam
    return "other"


def build_db(g, listens, sp_rows, sp_of_listen, lfm_rows, lfm_of_listen, dupe_rows, podcast_rows, video_rows,
             zz_extra) -> None:
    if FIXTURE_DB.exists():
        FIXTURE_DB.unlink()
    con = duckdb.connect(str(FIXTURE_DB))
    con.execute(SCHEMA_SQL.read_text())
    r = g.r
    p = lambda t: datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ")

    # ---- raw -------------------------------------------------------------------------
    raw_cols = [c for c in sp_rows[0] if c != "ip_addr"]
    def raw_tuple(row, fname, video):
        vals = [row[c] for c in raw_cols]
        vals[raw_cols.index("ts")] = p(row["ts"])
        return [fname, video, *vals]
    all_sp = [(row, f"Streaming_History_Audio_{row['ts'][:4]}.json", False) for row in sp_rows + podcast_rows]
    all_sp += [(row, "Streaming_History_Video_2024.json", True) for row in video_rows]
    insert(con, "raw_spotify", [raw_tuple(*x) for x in all_sp])
    lcols = ["uts", "utc_time", "artist", "artist_mbid", "album", "album_mbid", "track", "track_mbid"]
    insert(con, "raw_lastfm", [[row[c] if row[c] != "" else None for c in lcols] for row in lfm_rows])  # read_csv loads "" as NULL

    # ---- stg (W1 expected output) ----------------------------------------------------
    con.execute("""
        INSERT INTO stg_spotify
        SELECT row_number() OVER (ORDER BY ts, spotify_track_uri, ms_played, source_file),
               ts - to_milliseconds(ms_played), ts, ms_played, ms_played >= 30000, spotify_track_uri,
               master_metadata_album_artist_name, master_metadata_track_name, master_metadata_album_album_name,
               platform, NULL, conn_country, NULLIF(reason_start, ''), NULLIF(reason_end, ''),
               shuffle, skipped, offline, incognito_mode, NULL, NULL, NULL, NULL
        FROM raw_spotify WHERE spotify_track_uri IS NOT NULL AND NOT is_video""")
    fam_rows = [(platform_family(s), s) for s in PLATFORMS.values()]
    con.executemany("UPDATE stg_spotify SET platform_family = ? WHERE platform_raw = ?", fam_rows)
    con.execute("""
        CREATE TEMP TABLE lfm_ids AS
        SELECT row_number() OVER (ORDER BY uts, artist, track, album) AS lfm_id, * FROM raw_lastfm""")
    con.execute("""
        CREATE TEMP TABLE lfm_lag AS
        SELECT *, uts - lag(uts) OVER w AS gap, lag(lfm_id) OVER w AS prev_id
        FROM lfm_ids WINDOW w AS (PARTITION BY artist, track ORDER BY uts, lfm_id)""")
    con.execute("INSERT INTO lfm_self_dupes SELECT lfm_id, prev_id, gap FROM lfm_lag WHERE gap <= 60")
    con.execute("""
        INSERT INTO stg_lastfm
        SELECT lfm_id, to_timestamp(uts)::TIMESTAMPTZ AT TIME ZONE 'UTC', artist, track, NULLIF(album, ''),
               NULLIF(artist_mbid, ''), NULLIF(album_mbid, ''), NULLIF(track_mbid, ''), NULL, NULL, NULL, NULL
        FROM lfm_lag WHERE gap IS NULL OR gap > 60""")

    # id lookups by natural key
    sp_id = {(t, u, m): i for i, t, u, m in con.execute(
        "SELECT sp_id, strftime(ended_at_utc, '%Y-%m-%dT%H:%M:%SZ'), track_uri, ms_played FROM stg_spotify").fetchall()}
    lfm_id = {(u, a, t): i for i, u, a, t in con.execute(
        "SELECT lfm_id, uts, artist, track FROM lfm_ids").fetchall()}
    deduped = {i for (i,) in con.execute("SELECT lfm_id FROM lfm_self_dupes").fetchall()}

    # ---- truth -----------------------------------------------------------------------------
    con.execute("""CREATE TABLE truth_links (sp_ts TIMESTAMP, sp_uri VARCHAR, sp_ms BIGINT, lfm_uts BIGINT,
                   lfm_artist VARCHAR, lfm_track VARCHAR, matchable BOOLEAN, expected_pass TINYINT)""")
    con.execute("CREATE TABLE truth_lfm_dupes (uts BIGINT, artist VARCHAR, track VARCHAR)")
    insert(con, "truth_lfm_dupes", [(d["uts"], d["artist"], d["track"]) for d in dupe_rows])
    links: dict[int, tuple[int, int, int, float, float]] = {}  # listen idx -> (sp, lfm, pass, gap, score)
    truth = []
    for idx, li in enumerate(listens):
        if idx in sp_of_listen and idx in lfm_of_listen:
            s, lrow = sp_of_listen[idx], lfm_of_listen[idx]
            ts = p(s["ts"])
            start = ts - timedelta(milliseconds=s["ms_played"])
            gap = lrow["uts"] - start.replace(tzinfo=UTC).timestamp()
            if li.lfm_variant == "same":
                ok, mpass = -180 <= gap <= (ts - start).total_seconds() + 180, 1
                score = 100.0
            else:
                ok, mpass = abs(gap) <= 90, 2
                score = 100.0
            truth.append((ts, s["spotify_track_uri"], s["ms_played"], lrow["uts"], lrow["artist"], lrow["track"], ok, mpass))
            lid_ = lfm_id[(lrow["uts"], lrow["artist"], lrow["track"])]
            if ok and lid_ not in deduped:
                links[idx] = (sp_id[(s["ts"], s["spotify_track_uri"], s["ms_played"])],
                              lfm_id[(lrow["uts"], lrow["artist"], lrow["track"])], mpass, gap, score)
    insert(con, "truth_links", truth)
    insert(con, "match_links", list(links.values()))

    # ---- dimensions --------------------------------------------------------------------------
    A, AL, R = g.artists, g.albums, g.recs
    insert(con, "dim_artist", [
        (a.aid, a.name, a.norm, a.mbid, a.spotify_id, a.country, "Person" if " " in a.name else "Group",
         a.begin_year, None, a.listeners) for a in A.values()])
    insert(con, "dim_album", [
        (al.album_id, al.name, al.norm, al.artist, al.album_type, al.release_date, int(al.release_date[:4]),
         al.spotify_id, al.mbid) for al in AL.values()])
    rec_year = {rid: min(int(AL[alb].release_date[:4]) for _, alb in rec.uris) for rid, rec in R.items()}
    work_year: dict[tuple[int, str], int] = {}
    for rid, rec in R.items():
        k = (rec.artist, rec.base_norm)
        work_year[k] = min(work_year.get(k, 9999), rec_year[rid])

    def longform(rec: Recording) -> bool:
        kw = any(k in rec.full_norm.split() for k in ("mix", "set", "live"))
        return rec.duration_ms > 1_200_000 or (rec.duration_ms > 600_000 and kw)

    plays_per_rec = Counter(li.rec.rid for li in listens)
    dim_track = []
    for rid, rec in R.items():
        a = A[rec.artist]
        dim_track.append((rec.isrc, rec.isrc, rec.spotify_title(A), a.norm, rec.full_norm, rec.base_norm, rec.mix_norm,
                          bool(rec.mix_norm) and not rec.generic_mix, f"{a.norm}::{rec.base_norm}", rec.artist,
                          rec.uris[0][1], rec.duration_ms, "spotify", rec_year[rid],
                          work_year[(rec.artist, rec.base_norm)], longform(rec), a.listeners // 10))
    insert(con, "dim_track", dim_track)
    bridge = []
    for rec in R.values():
        bridge.append((rec.isrc, rec.artist, "primary", 1))
        if rec.featured is not None:
            bridge.append((rec.isrc, rec.featured, "featured", 1))
        if rec.remixer is not None:
            bridge.append((rec.isrc, rec.remixer, "remixer", 1))
    insert(con, "bridge_track_artist", bridge)
    insert(con, "track_uri_map", [(u, rec.isrc) for rec in R.values() for u, _ in rec.uris])
    key_map: dict[tuple[str, str], str] = {}
    for rec in sorted(R.values(), key=lambda x: -plays_per_rec[x.rid]):
        key_map.setdefault((A[rec.artist].norm, rec.full_norm), rec.isrc)
    insert(con, "track_key_map", [(*k, v) for k, v in key_map.items()])

    # ---- events, sessions, plays, skips ----------------------------------------------------------------
    ctz = TZ
    linked_lfm = {v[1] for v in links.values()}
    ev = []  # dicts in event order
    for idx, li in enumerate(listens):
        rec, a = li.rec, A[li.rec.artist]
        s = sp_of_listen.get(idx)
        lrow = lfm_of_listen.get(idx)
        lid = lfm_id[(lrow["uts"], lrow["artist"], lrow["track"])] if lrow else None
        if lid in deduped:  # a genuine scrobble the 60 s rule removes; the pipeline never sees it
            lid = None
        base = {"rec": rec, "artist": a, "listen": li, "idx": idx}
        if s is not None:
            sid = sp_id[(s["ts"], s["spotify_track_uri"], s["ms_played"])]
            linked = idx in links
            end = p(s["ts"])
            ev.append(dict(base, event_id=sid, sp_id=sid, lfm_id=lid if linked else None,
                           source="both" if linked else "spotify", start=end - timedelta(milliseconds=s["ms_played"]),
                           end=end, ms=s["ms_played"], conn=s["conn_country"], row=s,
                           match=links.get(idx)))
        if lid is not None and lid not in linked_lfm:
            start = datetime.fromtimestamp(lrow["uts"], UTC).replace(tzinfo=None)
            ev.append(dict(base, event_id=LASTFM_ONLY_ID_OFFSET + lid, sp_id=None, lfm_id=lid, source="lastfm",
                           start=start, end=start + timedelta(milliseconds=rec.duration_ms), ms=None, conn=None,
                           row=None, match=None))
    ev.sort(key=lambda e: (e["start"], e["event_id"]))
    for e in ev:
        e["is_skip"] = e["source"] == "spotify" and e["ms"] < 30_000

    # events table (W2 expected output)
    insert(con, "events", [(
        e["event_id"], e["sp_id"], e["lfm_id"], e["source"], e["start"], e["end"] if e["sp_id"] else None, e["ms"],
        e["is_skip"], e["row"]["spotify_track_uri"] if e["row"] else None,
        e["row"]["master_metadata_album_artist_name"] if e["row"] else lfm_of_listen[e["idx"]]["artist"],
        e["row"]["master_metadata_track_name"] if e["row"] else lfm_of_listen[e["idx"]]["track"],
        e["row"]["master_metadata_album_album_name"] if e["row"] else lfm_of_listen[e["idx"]]["album"],
        e["artist"].norm, e["rec"].full_norm if e["listen"].lfm_variant == "same" or e["sp_id"] else e["rec"].base_norm,
        e["rec"].base_norm, e["rec"].mix_norm if e["listen"].lfm_variant == "same" or e["sp_id"] else None,
        e["rec"].mbid, e["artist"].mbid,
        e["match"][2] if e["match"] else None, e["match"][3] if e["match"] else None) for e in ev])

    # country imputation: ZZ -> NULL; fill only when nearest known neighbours on both
    # sides are within 48 h and agree. Last.fm-only rows have no country.
    sp_ev = [e for e in ev if e["conn"] is not None]
    known = [(e["start"], None if e["conn"] == "ZZ" else e["conn"]) for e in sp_ev]
    prev_known: list[tuple[datetime, str] | None] = []
    last = None
    for t, c in known:
        prev_known.append(last)
        if c:
            last = (t, c)
    next_known: list[tuple[datetime, str] | None] = [None] * len(known)
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
        e["tz"] = ctz.get(e["country"] or "US", ctz["US"])
        e["local"] = e["start"].replace(tzinfo=UTC).astimezone(ZoneInfo(e["tz"])).replace(tzinfo=None)

    # sessions over plays and skips, running maximum of end times
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

    long_ids = {rid for rid, rec in R.items() if longform(rec)}
    ratios = [e["ms"] / e["rec"].duration_ms for e in ev
              if e["sp_id"] and e["ms"] >= 30_000 and e["rec"].rid not in long_ids]
    median_completion = statistics.median(ratios)
    con.execute("CREATE TABLE fixture_params (key VARCHAR, value DOUBLE)")
    con.execute("INSERT INTO fixture_params VALUES ('median_completion', ?)", [median_completion])

    fact_rows, skip_rows = [], []
    for e in ev:
        rec = e["rec"]
        row = e["row"]
        ms_imp = e["ms"] if e["ms"] is not None else int(rec.duration_ms * median_completion)
        ratio = None if e["ms"] is None or rec.rid in long_ids else min(e["ms"] / rec.duration_ms, 1.0)
        m = e["match"]
        t = (e["event_id"], e["start"], e["end"], e["local"], e["tz"], e["country"], e["imputed"], rec.isrc,
             rec.artist, rec.uris[0][1] if row is None else dict(rec.uris)[row["spotify_track_uri"]],
             e["session_id"], e["session_index"], e["new10"], e["new30"], e["ms"], ms_imp, ratio, e["source"],
             m[2] if m else None, m[3] if m else None,
             platform_family(row["platform"]) if row else None, row["shuffle"] if row else None,
             row["offline"] if row else None, row["incognito_mode"] if row else None,
             (row["reason_start"] or None) if row else None, (row["reason_end"] or None) if row else None,
             row["skipped"] if row else None)
        (skip_rows if e["is_skip"] else fact_rows).append(t)
    insert(con, "plays", fact_rows)
    insert(con, "skips", skip_rows)

    srows = []
    for s_id, es in sess.items():
        fams = Counter(platform_family(e["row"]["platform"]) for e in es if e["row"])
        srcs = {e["source"] for e in es}
        srows.append((s_id, es[0]["start"], max(e["end"] for e in es), es[0]["local"], es[0]["tz"],
                      sum(not e["is_skip"] for e in es), sum(e["is_skip"] for e in es),
                      sum(e["ms"] if e["ms"] is not None else int(e["rec"].duration_ms * median_completion) for e in es),
                      fams.most_common(1)[0][0] if fams else None, srcs.pop() if len(srcs) == 1 else "mixed"))
    insert(con, "sessions", srows)

    # ---- enrichment caches (parsed) -------------------------------------------------------------
    now = datetime(2026, 10, 22, 0, 0)
    con.execute("""INSERT INTO enr_local_duration
                   SELECT track_uri, max(ms_played), count(*) FROM stg_spotify
                   WHERE reason_end = 'trackdone' AND NOT skipped GROUP BY 1""")
    sp_tracks = []
    sp_ = g.special  # scenario recordings never 404, so their acceptance checks stay reachable
    scenario_rids = {sp_["binge"], sp_["djmix"], sp_["longtrack"], sp_["glass"], sp_["paper"], sp_["remaster"],
                     *sp_["remix_recs"]}
    for rec in R.values():
        for uri, alb_id in rec.uris:
            al = AL[alb_id]
            if r.random() < 0.02 and rec.rid not in scenario_rids:  # draw first: keeps the random stream intact
                sp_tracks.append((uri, None, None, None, None, None, None, None, None, None, None, 404, now))
                continue
            artists = [{"id": A[rec.artist].spotify_id, "name": A[rec.artist].name}]
            if rec.featured is not None:
                artists.append({"id": A[rec.featured].spotify_id, "name": A[rec.featured].name})
            sp_tracks.append((uri, rec.isrc, rec.spotify_title(A), rec.duration_ms, False, al.spotify_id, al.name,
                              al.album_type, al.release_date, "day", artists, 200, now))
    insert(con, "enr_spotify_track", sp_tracks)
    insert(con, "enr_spotify_artist", [
        (a.spotify_id, a.name, [a.genre] if r.random() < 0.5 else [], 200, now) for a in A.values()])
    insert(con, "enr_mb_artist", [
        (a.mbid, a.name, "Person", a.country, a.begin_year, None, [a.genre], 200, now) for a in A.values() if a.mbid])
    mb = []
    for rec in R.values():
        if rec.mbid:
            mb.append(("mbid", rec.mbid, rec.mbid, rec.base_title, rec.duration_ms, [rec.isrc],
                       f"{rec_year[rec.rid]}-01-01", [{"mbid": A[rec.artist].mbid, "name": A[rec.artist].name,
                                                       "joinphrase": ""}], [A[rec.artist].genre], None, 200, now))
    insert(con, "enr_mb_recording", mb)
    tags = []
    for a in A.values():
        tags += [("artist", a.norm, a.genre, 100, now), ("artist", a.norm, "seen live", 20, now),
                 ("artist", a.norm, "favorites", 8, now), ("artist", a.norm, str(a.begin_year), 4, now)]
    for rec in sorted(R.values(), key=lambda x: -plays_per_rec[x.rid])[:60]:
        tags.append(("track", f"{A[rec.artist].norm}::{rec.full_norm}", A[rec.artist].genre, 100, now))
    insert(con, "enr_lastfm_tags", list({t[:3]: t for t in tags}.values()))
    info = [("artist", a.norm, a.mbid, a.listeners, a.listeners * 12, None, 200, now) for a in A.values()]
    info += [("track", f"{A[rec.artist].norm}::{rec.full_norm}", rec.mbid, A[rec.artist].listeners // 10, None,
              rec.duration_ms, 200, now) for rec in R.values()]
    insert(con, "enr_lastfm_info", list({i[:2]: i for i in info}.values()))
    dz = []
    for rec in R.values():
        if r.random() < 0.6:
            bpm = GENRE_BPM[A[rec.artist].genre] + r.uniform(-6, 6)
            bpm = None if r.random() < 0.1 else (bpm * 2 if r.random() < 0.05 else bpm)
            dz.append((rec.isrc, r.randint(1, 10**9), bpm, r.uniform(-12, -4), rec.duration_ms,
                       f"{rec_year[rec.rid]}-01-01", 200, now))
    insert(con, "enr_deezer_track", dz)

    # ---- genre -------------------------------------------------------------------------------------
    parent = {"indie rock": "rock", "electro house": "electronic", "dubstep": "electronic", "house": "electronic",
              "techno": "electronic", "ambient": "electronic", "hip hop": "hip hop", "k-pop": "pop", "v-pop": "pop",
              "j-pop": "pop"}
    gm = [(t, t, pg, True, t == pg) for t, pg in parent.items()]
    gm += [("seen live", None, None, False, False), ("favorites", None, None, False, False)]
    gm += [(str(y), None, None, False, False) for y in range(1995, 2019)]
    insert(con, "genre_map", gm)
    insert(con, "track_genre", [
        (rec.isrc, parent[A[rec.artist].genre], A[rec.artist].genre, 1.0, "artist") for rec in R.values()])

    con.execute("CREATE TABLE fixture_scenarios (scenario VARCHAR, key VARCHAR, value VARCHAR)")
    g.scenarios.append(("country", "isolated_zz_rows", str(len(zz_extra))))
    planted = {lfm_id[(d["uts"], d["artist"], d["track"])] for d in dupe_rows}
    g.scenarios.append(("lfm_dupes", "planted", str(len(planted))))
    g.scenarios.append(("lfm_dupes", "collateral", str(len(deduped - planted))))
    insert(con, "fixture_scenarios", g.scenarios)
    con.close()

    n_sp, n_lfm = len(sp_rows), len(lfm_rows)
    print(f"fixture: {n_sp} spotify rows, {len(podcast_rows)} podcast, {len(video_rows)} video, {n_lfm} scrobbles "
          f"({len(dupe_rows)} dupes), {len(links)} matchable links, {len(fact_rows)} plays, {len(skip_rows)} skips, "
          f"{len(srows)} sessions -> {FIXTURE_DB.name}")
    expected_dupes = {lfm_id[(d["uts"], d["artist"], d["track"])] for d in dupe_rows}
    assert expected_dupes <= deduped, "a planted double scrobble survived self-dedupe"


if __name__ == "__main__":
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
        FIXTURE_DB, FIXTURE_RAW_DIR = out / "dev_fixtures.duckdb", out / "raw"
    main()
