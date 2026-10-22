"""Title and artist normalisation. The only place these rules live (see specs/W2_match.md).

normalize_title(s) -> (full_norm, base_norm, mix_desc | None)
normalize_artist(s) -> artist_norm
"""

from __future__ import annotations

import re
import unicodedata
from functools import cache

# Feat clauses: bracketed anywhere, or trailing after the title / artist.
_FEAT_BRACKET_RE = re.compile(r"\s*[(\[]\s*(?:feat\.?|ft\.?|featuring|with)\s[^)\]]*[)\]]", re.IGNORECASE)
_FEAT_TRAILING_RE = re.compile(r"\s+(?:feat\.|ft\.|featuring\s)\s*.*$", re.IGNORECASE)

# Remaster noise. Never touches Live / Acoustic / Demo: those are different recordings.
_REMASTER = r"(?:\d{4}\s+)?(?:digital(?:ly)?\s+)?remaster(?:ed)?(?:\s+\d{4})?(?:\s+version)?"
NOISE_RE = re.compile(
    rf"\s*[(\[]\s*{_REMASTER}\s*[)\]]|\s+[-\u2013\u2014]\s+{_REMASTER}\s*$",
    re.IGNORECASE,
)

# Mix descriptors: a bracketed segment, or a trailing " - " segment, with one of these words.
_MIX_WORD_RE = re.compile(r"\b(?:remix|mix|vip|edit|bootleg|flip|rework|dub|version)\b", re.IGNORECASE)
MIX_RE = re.compile(r"[(\[]([^)\]]*)[)\]]")
_DASH_RE = re.compile(r"\s+[-\u2013\u2014]\s+")

GENERIC_MIX = frozenset({
    "original mix", "extended mix", "radio edit", "album version", "original version", "extended version",
    "single version", "radio version", "extended", "edit", "radio mix", "single edit",
})

_APOSTROPHES = dict.fromkeys(map(ord, "'\u2019\u2018`\u00b4"), None)


@cache
def normalize_text(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).casefold()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not "\u0300" <= c <= "\u036f")
    s = unicodedata.normalize("NFC", s.replace("\u0111", "d"))
    s = s.translate(_APOSTROPHES).replace("&", " and ")
    # Keep letters, digits and combining marks (Indic vowel signs, kana dakuten); all else -> space.
    out = [c if c.isalnum() or unicodedata.category(c)[0] == "M" else " " for c in s]
    return " ".join("".join(out).split())


def _strip_feat(s: str) -> str:
    s = _FEAT_BRACKET_RE.sub("", s)
    return _FEAT_TRAILING_RE.sub("", s)


def is_generic_mix(mix_desc: str | None) -> bool:
    return mix_desc is None or mix_desc in GENERIC_MIX


@cache
def normalize_title(s: str | None) -> tuple[str, str, str | None]:
    if not s:
        return "", "", None
    s = NOISE_RE.sub("", _strip_feat(s)).strip()
    mixes: list[str] = []

    def take(m: re.Match) -> str:
        if _MIX_WORD_RE.search(m.group(1)):
            mixes.append(m.group(1))
            return " "
        return m.group(0)

    s = MIX_RE.sub(take, s)
    dashes = list(_DASH_RE.finditer(s))
    if dashes and _MIX_WORD_RE.search(s[dashes[-1].end():]):
        mixes.append(s[dashes[-1].end():])
        s = s[: dashes[-1].start()]
    base = normalize_text(s)
    mix = " ".join(m for m in (normalize_text(x) for x in mixes) if m) or None
    full = f"{base} ({mix})" if mix else base
    return full, base, mix


@cache
def normalize_artist(s: str | None) -> str:
    if not s:
        return ""
    return normalize_text(_strip_feat(s))


@cache
def normalize_album(s: str | None) -> str:
    """album_norm: remaster noise removed, then the shared text rules."""
    if not s:
        return ""
    return normalize_text(NOISE_RE.sub("", s))


_MIX_CREDIT_RE = re.compile(r"^(.*?)\s*\b(?:remix|mix|edit|rework|bootleg|flip|dub|vip)$")


@cache
def mix_credit(mix_desc: str | None) -> str | None:
    """The artist credited in a mix descriptor: the text before a trailing remix/mix/edit/... word,
    normalised as an artist. 'kilo vantage remix' -> 'kilo vantage'. None when nothing precedes it."""
    if not mix_desc:
        return None
    m = _MIX_CREDIT_RE.match(normalize_text(mix_desc))
    if not m:
        return None
    return normalize_artist(m.group(1)) or None
