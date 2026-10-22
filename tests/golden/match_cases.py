"""Golden cases for the two-pass matcher (pipeline/match.py, W2).

Each case is an isolated mini-history. Times are seconds relative to
BASE_UTC. A Spotify row S(id, artist, track, start, ms) has
started_at_utc = BASE + start and ended_at_utc = BASE + start + ms/1000
(that is, ts = end, start = ts - ms_played, as in the export). A Last.fm row
L(id, artist, track, t) was scrobbled at BASE + t.

`expect` maps (sp_id, lfm_id) -> match_pass for every pair that must be
linked. Any link not listed is a failure, so unlisted rows must stay unmatched.

Matcher rules these encode (full text in specs/W2_match.md):
  candidates  artist_norm equal OR base_norm equal, artist token_set_ratio >= 85
  pass 1      full_norm ratio >= 92, scrobble in [start - 180 s, end + 180 s]
  pass 2      base_norm ratio >= 92, |scrobble - start| <= 90 s, and the
              mix guardrail: one side has no mix_desc or a generic one
              (original mix, extended mix, radio edit, album version, ...),
              or both are equal
  greedy      1-to-1 over all candidates of both passes, sorted by
              is_full_listen DESC, pass ASC, |gap| ASC, score DESC
"""

from datetime import datetime
from typing import NamedTuple

BASE_UTC = datetime(2024, 5, 4, 18, 0, 0)


class S(NamedTuple):
    id: int
    artist: str
    track: str
    start: float
    ms: int


class L(NamedTuple):
    id: int
    artist: str
    track: str
    t: float


class Case(NamedTuple):
    id: str
    desc: str
    sp: list
    lfm: list
    expect: dict


CASES = [
    # --- 1. Exact matches and normal scrobble offsets -----------------------
    Case("M01", "exact names, scrobble 0.6 s before start",
         [S(1, "Daft Punk", "Digital Love", 0, 301_000)],
         [L(1, "Daft Punk", "Digital Love", -0.6)], {(1, 1): 1}),
    Case("M02", "exact names, scrobble 1.5 s after start",
         [S(1, "Daft Punk", "Digital Love", 0, 301_000)],
         [L(1, "Daft Punk", "Digital Love", 1.5)], {(1, 1): 1}),
    Case("M03", "case and whitespace differ",
         [S(1, "deadmau5", "Strobe", 0, 634_000)],
         [L(1, "Deadmau5", "strobe ", 2)], {(1, 1): 1}),
    Case("M04", "scrobble at the very end of the pass-1 window (start - 179 s)",
         [S(1, "Burial", "Archangel", 0, 239_000)],
         [L(1, "Burial", "Archangel", -179)], {(1, 1): 1}),
    Case("M05", "scrobble 170 s after the play ended (inside end + 180 s)",
         [S(1, "Burial", "Archangel", 0, 239_000)],
         [L(1, "Burial", "Archangel", 239 + 170)], {(1, 1): 1}),
    Case("M06", "mobile drift +75 s", [S(1, "Disclosure", "Latch", 0, 255_000)],
         [L(1, "Disclosure", "Latch", 75)], {(1, 1): 1}),
    Case("M07", "mobile drift -85 s", [S(1, "Disclosure", "Latch", 0, 255_000)],
         [L(1, "Disclosure", "Latch", -85)], {(1, 1): 1}),

    # --- 2. Outside the window ----------------------------------------------
    Case("M08", "scrobble 4 min after the play ended",
         [S(1, "Burial", "Archangel", 0, 239_000)],
         [L(1, "Burial", "Archangel", 239 + 240)], {}),
    Case("M09", "scrobble 4 min before the play started",
         [S(1, "Burial", "Archangel", 0, 239_000)],
         [L(1, "Burial", "Archangel", -240)], {}),
    Case("M10", "long pause: true start 10 min before ts - ms_played (documented miss)",
         [S(1, "Bonobo", "Kerala", 0, 240_000)],
         [L(1, "Bonobo", "Kerala", -600)], {}),

    # --- 3. Skip then replay (4-tier priority) ------------------------------
    Case("M11", "5 s false start, replay 6 s later; scrobble nearer the false start",
         [S(1, "Robyn", "Dancing On My Own", 0, 5_000), S(2, "Robyn", "Dancing On My Own", 6, 281_000)],
         [L(1, "Robyn", "Dancing On My Own", 1)], {(2, 1): 1}),
    Case("M12", "two false starts then a full play",
         [S(1, "Robyn", "Hang With Me", 0, 3_000), S(2, "Robyn", "Hang With Me", 4, 8_000),
          S(3, "Robyn", "Hang With Me", 13, 260_000)],
         [L(1, "Robyn", "Hang With Me", 4)], {(3, 1): 1}),
    Case("M13", "full play at a pass-2 candidate beats a 2 s pass-1 false start",
         [S(1, "Fred again..", "Delilah (pull me out of this)", 0, 2_000),
          S(2, "Fred again..", "Delilah (pull me out of this) - Extended Mix", 30, 380_000)],
         [L(1, "Fred again..", "Delilah (pull me out of this)", 1)], {(2, 1): 2}),
    Case("M14", "skip with no scrobble stays Spotify-only",
         [S(1, "Robyn", "Indestructible", 0, 12_000)], [], {}),
    Case("M15", "skip of song A, full play of song B, one scrobble of B",
         [S(1, "Robyn", "Indestructible", 0, 12_000), S(2, "Robyn", "Call Your Girlfriend", 12, 219_000)],
         [L(1, "Robyn", "Call Your Girlfriend", 12)], {(2, 1): 1}),

    # --- 4. Repeat listening -------------------------------------------------
    Case("M16", "same song three times back to back, three scrobbles",
         [S(1, "Charli XCX", "Von dutch", 0, 114_000), S(2, "Charli XCX", "Von dutch", 114, 114_000),
          S(3, "Charli XCX", "Von dutch", 228, 114_000)],
         [L(1, "Charli XCX", "Von dutch", 0), L(2, "Charli XCX", "Von dutch", 114),
          L(3, "Charli XCX", "Von dutch", 228)],
         {(1, 1): 1, (2, 2): 1, (3, 3): 1}),
    Case("M17", "three plays, two scrobbles: the unscrobbled middle play stays Spotify-only",
         [S(1, "Charli XCX", "360", 0, 133_000), S(2, "Charli XCX", "360", 133, 133_000),
          S(3, "Charli XCX", "360", 266, 133_000)],
         [L(1, "Charli XCX", "360", 0), L(3, "Charli XCX", "360", 266)],
         {(1, 1): 1, (3, 3): 1}),
    Case("M18", "short track looped, scrobbles drift +20 s",
         [S(1, "Aphex Twin", "Avril 14th", 0, 125_000), S(2, "Aphex Twin", "Avril 14th", 125, 125_000)],
         [L(1, "Aphex Twin", "Avril 14th", 20), L(2, "Aphex Twin", "Avril 14th", 145)],
         {(1, 1): 1, (2, 2): 1}),
    Case("M19", "two plays, one scrobble: nearest start wins",
         [S(1, "Charli XCX", "Apple", 0, 151_000), S(2, "Charli XCX", "Apple", 151, 151_000)],
         [L(1, "Charli XCX", "Apple", 150)], {(2, 1): 1}),

    # --- 5. Title noise -------------------------------------------------------
    Case("M20", "remaster suffix on Spotify only",
         [S(1, "Queen", "Don't Stop Me Now - Remastered 2011", 0, 209_000)],
         [L(1, "Queen", "Don't Stop Me Now", 0)], {(1, 1): 1}),
    Case("M21", "remaster in brackets on Last.fm only",
         [S(1, "David Bowie", "Heroes", 0, 371_000)],
         [L(1, "David Bowie", "Heroes (2017 Remaster)", 1)], {(1, 1): 1}),
    Case("M22", "feat. in title on one side",
         [S(1, "Daft Punk", "Get Lucky (feat. Pharrell Williams & Nile Rodgers)", 0, 369_000)],
         [L(1, "Daft Punk", "Get Lucky", 0)], {(1, 1): 1}),
    Case("M23", "feat. in artist on Last.fm",
         [S(1, "Major Lazer", "Lean On", 0, 176_000)],
         [L(1, "Major Lazer feat. MØ & DJ Snake", "Lean On", 0)], {(1, 1): 1}),
    Case("M24", "joint artist credit vs primary artist",
         [S(1, "Disclosure", "You & Me - Flume Remix", 0, 284_000)],
         [L(1, "Disclosure & Eliza Doolittle", "You & Me (Flume Remix)", 0)], {(1, 1): 1}),
    Case("M25", "curly vs straight apostrophe",
         [S(1, "Rihanna", "Don’t Stop the Music", 0, 267_000)],
         [L(1, "Rihanna", "Don't Stop The Music", 0)], {(1, 1): 1}),
    Case("M26", "accented vs plain artist",
         [S(1, "Beyoncé", "Halo", 0, 261_000)], [L(1, "Beyonce", "Halo", 0)], {(1, 1): 1}),
    Case("M27", "& vs and",
         [S(1, "Simon & Garfunkel", "America", 0, 214_000)],
         [L(1, "Simon and Garfunkel", "America", 0)], {(1, 1): 1}),
    Case("M28", "'n' contraction spelled differently",
         [S(1, "Justice", "Ghosts 'n' Stuff", 0, 254_000)],
         [L(1, "Justice", "Ghosts n Stuff", 1)], {(1, 1): 1}),
    Case("M29", "Vietnamese diacritics stripped on one side",
         [S(1, "Sơn Tùng M-TP", "Nơi Này Có Anh", 0, 260_000)],
         [L(1, "Son Tung M-TP", "Noi Nay Co Anh", 0)], {(1, 1): 1}),
    Case("M30", "identical Japanese strings",
         [S(1, "YOASOBI", "夜に駆ける", 0, 261_000)], [L(1, "YOASOBI", "夜に駆ける", 0)], {(1, 1): 1}),
    Case("M31", "identical Korean strings",
         [S(1, "Girls' Generation", "다시 만난 세계", 0, 230_000)],
         [L(1, "Girls' Generation", "다시 만난 세계", 0)], {(1, 1): 1}),
    Case("M32", "one-character typo passes fuzzy pass 1",
         [S(1, "M83", "Midnight City", 0, 243_000)], [L(1, "M83", "Midnight Citty", 0)], {(1, 1): 1}),

    # --- 6. Mix descriptors ---------------------------------------------------
    Case("M33", "dash vs bracket remix syntax is pass 1",
         [S(1, "Bonobo", "Kerala - Fred again.. Remix", 0, 250_000)],
         [L(1, "Bonobo", "Kerala (Fred again.. Remix)", 0)], {(1, 1): 1}),
    Case("M34", "square brackets vs round brackets",
         [S(1, "Rüfüs Du Sol", "Innerbloom [What So Not Remix]", 0, 310_000)],
         [L(1, "RÜFÜS DU SOL", "Innerbloom (What So Not Remix)", 0)], {(1, 1): 1}),
    Case("M35", "Extended Mix vs plain title, 40 s apart -> pass 2",
         [S(1, "Fisher", "Losing It - Extended Mix", 0, 395_000)],
         [L(1, "FISHER", "Losing It", 40)], {(1, 1): 2}),
    Case("M36", "Original Mix vs plain title, -60 s -> pass 2",
         [S(1, "Eric Prydz", "Opus", 0, 543_000)],
         [L(1, "Eric Prydz", "Opus (Original Mix)", -60)], {(1, 1): 2}),
    Case("M37", "Extended Mix vs plain title, 150 s apart -> no match (outside ±90 s)",
         [S(1, "Fisher", "Losing It - Extended Mix", 0, 395_000)],
         [L(1, "FISHER", "Losing It", 150)], {}),
    Case("M38", "conflicting explicit remixes are never merged",
         [S(1, "Bonobo", "Kerala - Fred again.. Remix", 0, 250_000)],
         [L(1, "Bonobo", "Kerala (Maceo Plex Remix)", 3)], {}),
    Case("M39", "conflicting remixes, both 1 s apart, plus the matching remix 30 s later",
         [S(1, "Disclosure", "Latch - Kaytranada Remix", 0, 245_000)],
         [L(1, "Disclosure", "Latch (Joe Goddard Remix)", 1), L(2, "Disclosure", "Latch (Kaytranada Remix)", 30)],
         {(1, 2): 1}),
    Case("M40", "explicit remix vs plain title -> pass 2",
         [S(1, "Odesza", "Say My Name (RAC Remix)", 0, 254_000)],
         [L(1, "ODESZA", "Say My Name", 10)], {(1, 1): 2}),
    Case("M41", "Radio Edit vs Original Mix (both generic) -> pass 2",
         [S(1, "Avicii", "Levels - Radio Edit", 0, 199_000)],
         [L(1, "Avicii", "Levels (Original Mix)", 20)], {(1, 1): 2}),
    Case("M42", "explicit remix vs Extended Mix (one generic) -> pass 2",
         [S(1, "Avicii", "Levels - Skrillex Remix", 0, 268_000)],
         [L(1, "Avicii", "Levels (Extended Mix)", 5)], {(1, 1): 2}),
    Case("M43", "VIP vs remix of the same title -> conflict, no match",
         [S(1, "Skrillex", "Bangarang (VIP)", 0, 215_000)],
         [L(1, "Skrillex", "Bangarang (Kill The Noise Remix)", 0)], {}),

    # --- 7. Pass and tie-break priority --------------------------------------
    Case("M44", "pass 1 at 60 s beats pass 2 at 5 s for the same scrobble",
         [S(1, "Fisher", "Losing It", 60, 240_000), S(2, "Fisher", "Losing It - Extended Mix", -5, 395_000)],
         [L(1, "FISHER", "Losing It", 0)], {(1, 1): 1}),
    Case("M45", "pass 2 leftover still links once pass 1 has claimed its pair",
         [S(1, "Fisher", "Losing It", 0, 240_000), S(2, "Fisher", "Losing It - Extended Mix", 240, 395_000)],
         [L(1, "FISHER", "Losing It", 0), L(2, "FISHER", "Losing It", 260)],
         {(1, 1): 1, (2, 2): 2}),
    Case("M46", "equal gaps: higher fuzzy score wins",
         [S(1, "M83", "Midnight City", 0, 243_000)],
         [L(1, "M83", "Midnight Citty", -10), L(2, "M83", "Midnight City", 10)], {(1, 2): 1}),
    Case("M47", "each scrobble claimed once even when two plays overlap (two devices)",
         [S(1, "Tame Impala", "The Less I Know The Better", 0, 216_000),
          S(2, "Tame Impala", "The Less I Know The Better", 3, 216_000)],
         [L(1, "Tame Impala", "The Less I Know The Better", 1)], {(1, 1): 1}),

    # --- 8. Different songs and different artists ----------------------------
    Case("M48", "adjacent different songs by one artist do not cross-match",
         [S(1, "Radiohead", "Reckoner", 0, 290_000), S(2, "Radiohead", "Nude", 290, 255_000)],
         [L(1, "Radiohead", "Reckoner", 0), L(2, "Radiohead", "Nude", 290)],
         {(1, 1): 1, (2, 2): 1}),
    Case("M49", "same title, different artist (cover) -> no match",
         [S(1, "Jeff Buckley", "Hallelujah", 0, 413_000)],
         [L(1, "Leonard Cohen", "Hallelujah", 0)], {}),
    Case("M50", "same artist, different song at the same moment -> no match",
         [S(1, "Radiohead", "Reckoner", 0, 290_000)],
         [L(1, "Radiohead", "Weird Fishes/Arpeggi", 0)], {}),
    Case("M51", "similar but distinct titles stay apart",
         [S(1, "Daft Punk", "Around the World", 0, 429_000)],
         [L(1, "Daft Punk", "Around the World / Harder Better Faster Stronger", 0)], {}),
    Case("M52", "a live version is a different title, no match",
         [S(1, "Florence + The Machine", "Dog Days Are Over", 0, 252_000)],
         [L(1, "Florence + The Machine", "Dog Days Are Over - Live", 0)], {}),
    Case("M53", "the artist name differs by more than the threshold",
         [S(1, "The Chemical Brothers", "Galvanize", 0, 393_000)],
         [L(1, "Chemical Bros", "Galvanize", 0)], {}),

    # --- 9. One source only ---------------------------------------------------
    Case("M54", "Last.fm only (another player)", [],
         [L(1, "Burial", "Archangel", 0)], {}),
    Case("M55", "Spotify only (scrobbler off)",
         [S(1, "Burial", "Archangel", 0, 239_000)], [], {}),

    # --- 10. Longer sequences ---------------------------------------------------
    Case("M56", "album run with one scrobble missing",
         [S(1, "Daft Punk", "Give Life Back to Music", 0, 274_000),
          S(2, "Daft Punk", "The Game of Love", 274, 321_000),
          S(3, "Daft Punk", "Giorgio by Moroder", 595, 544_000),
          S(4, "Daft Punk", "Within", 1139, 228_000)],
         [L(1, "Daft Punk", "Give Life Back to Music", 0), L(2, "Daft Punk", "The Game of Love", 274),
          L(4, "Daft Punk", "Within", 1139)],
         {(1, 1): 1, (2, 2): 1, (4, 4): 1}),
    Case("M57", "shuffle with skips interleaved",
         [S(1, "Jamie xx", "Gosh", 0, 9_000), S(2, "Jamie xx", "Loud Places", 9, 283_000),
          S(3, "Jamie xx", "Sleep Sound", 292, 4_000), S(4, "Jamie xx", "Gosh", 296, 295_000)],
         [L(2, "Jamie xx", "Loud Places", 9), L(4, "Jamie xx", "Gosh", 296)],
         {(2, 2): 1, (4, 4): 1}),
    Case("M58", "offline batch: all scrobbles drift +80 s",
         [S(1, "Four Tet", "Baby", 0, 270_000), S(2, "Four Tet", "Teenage Birdsong", 270, 223_000)],
         [L(1, "Four Tet", "Baby", 80), L(2, "Four Tet", "Teenage Birdsong", 350)],
         {(1, 1): 1, (2, 2): 1}),
    Case("M59", "Last.fm double scrobble already removed upstream; the leftover second scrobble of a replay matches the replay",
         [S(1, "Caribou", "Can't Do Without You", 0, 236_000), S(2, "Caribou", "Can't Do Without You", 236, 236_000)],
         [L(1, "Caribou", "Can't Do Without You", 0), L(2, "Caribou", "Can't Do Without You", 237)],
         {(1, 1): 1, (2, 2): 1}),
    Case("M60", "remix played after the original, scrobbles for both",
         [S(1, "Disclosure", "Latch", 0, 255_000), S(2, "Disclosure", "Latch - Kaytranada Remix", 255, 245_000)],
         [L(1, "Disclosure", "Latch", 0), L(2, "Disclosure", "Latch (Kaytranada Remix)", 255)],
         {(1, 1): 1, (2, 2): 1}),
]
