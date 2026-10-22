"""Golden cases for pipeline/normalize.py (W2 must pass all of them).

Each title case is (raw_title, full_norm, base_norm, mix_desc).
Each artist case is (raw_artist, artist_norm).

Rules these encode (see specs/W2_match.md for the full spec):
  * NFKC + casefold, Latin accents stripped (only U+0300-U+036F combining
    marks are dropped, so Japanese dakuten survive; 'đ' -> 'd'), apostrophes deleted, '&' -> 'and',
    any other non-word run -> one space. CJK and Hangul are kept.
  * feat./ft./featuring clauses removed (bracketed or trailing); '(with X)' removed.
  * remaster noise removed: '- 2011 Remaster', '(Remastered 2009)', '- Remastered'.
  * a bracketed segment, or a trailing ' - ' segment, containing
    remix|mix|vip|edit|bootleg|flip|rework|dub|version becomes mix_desc;
    full_norm = 'base_norm (mix_desc)'.
"""

TITLE_CASES = [
    ("Strobe", "strobe", "strobe", None),
    ("  Strobe  ", "strobe", "strobe", None),
    ("Don’t Stop Me Now", "dont stop me now", "dont stop me now", None),
    ("Don't Stop Me Now - 2011 Remaster", "dont stop me now", "dont stop me now", None),
    ("Heroes (Remastered 2009)", "heroes", "heroes", None),
    ("Heroes - Remastered", "heroes", "heroes", None),
    ("Wonderwall - Remastered 2014", "wonderwall", "wonderwall", None),
    ("Get Lucky (feat. Pharrell Williams)", "get lucky", "get lucky", None),
    ("Get Lucky (ft. Pharrell Williams & Nile Rodgers)", "get lucky", "get lucky", None),
    ("Stay (with Justin Bieber)", "stay", "stay", None),
    ("Lean On feat. MØ", "lean on", "lean on", None),
    ("Opus - Four Tet Remix", "opus (four tet remix)", "opus", "four tet remix"),
    ("Opus (Four Tet Remix)", "opus (four tet remix)", "opus", "four tet remix"),
    ("Opus [Four Tet Remix]", "opus (four tet remix)", "opus", "four tet remix"),
    ("Language (Extended Mix)", "language (extended mix)", "language", "extended mix"),
    ("Language - Original Mix", "language (original mix)", "language", "original mix"),
    ("Midnight City - Radio Edit", "midnight city (radio edit)", "midnight city", "radio edit"),
    ("Animals (VIP)", "animals (vip)", "animals", "vip"),
    ("Levels - Skrillex Remix (feat. Etta James)", "levels (skrillex remix)", "levels", "skrillex remix"),
    ("Sweet Disposition (Live at Glastonbury)", "sweet disposition live at glastonbury", "sweet disposition live at glastonbury", None),
    ("Ghosts 'n' Stuff", "ghosts n stuff", "ghosts n stuff", None),
    ("Beyoncé", "beyonce", "beyonce", None),
    ("Rock & Roll", "rock and roll", "rock and roll", None),
    ("Ｆｕｌｌｗｉｄｔｈ", "fullwidth", "fullwidth", None),
    ("夜に駆ける", "夜に駆ける", "夜に駆ける", None),
    ("다시 만난 세계", "다시 만난 세계", "다시 만난 세계", None),
    ("ずっと真夜中でいいのに", "ずっと真夜中でいいのに", "ずっと真夜中でいいのに", None),
    ("Nơi Này Có Anh", "noi nay co anh", "noi nay co anh", None),
    ("Song - Live", "song live", "song live", None),
    ("One More Time - Short Radio Edit", "one more time (short radio edit)", "one more time", "short radio edit"),
    ("Titanium (David Guetta Bootleg) - 2012 Remaster", "titanium (david guetta bootleg)", "titanium", "david guetta bootleg"),
]

ARTIST_CASES = [
    ("Daft Punk", "daft punk"),
    ("Beyoncé", "beyonce"),
    ("Simon & Garfunkel", "simon and garfunkel"),
    ("Major Lazer feat. MØ", "major lazer"),
    ("Calvin Harris ft. Rihanna", "calvin harris"),
    ("AC/DC", "ac dc"),
    ("방탄소년단", "방탄소년단"),
    ("Sơn Tùng M-TP", "son tung m tp"),
    ("Đen Vâu", "den vau"),
    ("  The  xx ", "the xx"),
]
