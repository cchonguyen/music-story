# W2: normalisation and two-pass matcher

Tier: Opus, high effort (maxTurns 40). Deliverables: `pipeline/normalize.py`, `pipeline/match.py`.

## Read only
- `sql/schema.sql`: stg_spotify, stg_lastfm, match_links, events
- `tests/golden/normalize_cases.py`, `tests/golden/match_cases.py` (the rules are in their docstrings)
- `tests/test_normalize_golden.py`, `tests/test_match_golden.py`, `tests/test_match_fixture.py`

## normalize.py
`normalize_title(s) -> (full_norm, base_norm, mix_desc | None)` and `normalize_artist(s) -> str`.
- Text: NFKC, casefold, NFKD then drop only U+0300-U+036F, `đ` -> `d`, NFC; delete apostrophes
  (`' ’ ‘ \` ´`); `&` -> ` and `; every other non-word run (and `_`) -> one space; trim.
- Before text normalisation: remove feat clauses (`(feat. X)`, `[ft. X]`, `(featuring X)`, `(with X)`,
  trailing `feat. X` / `ft. X`), and remaster noise (`- 2011 Remaster`, `(Remastered 2009)`,
  `- Remastered`, `(2017 Remaster)`).
- NOISE_RE never touches `Live`, `Acoustic`, `Demo`: those are different recordings.
- MIX_RE: a `( )` / `[ ]` segment, or a trailing ` - ` segment, containing
  remix|mix|vip|edit|bootleg|flip|rework|dub|version is removed from the base and becomes mix_desc
  (several segments join with one space). full_norm = `base_norm (mix_desc)` or base_norm.
- Generic descriptors: original mix, extended mix, radio edit, album version, original version,
  extended version, single version, radio version, extended, edit, radio mix, single edit.

## match.py
`run(con)` reads stg tables, fills their norm columns, rewrites match_links and events.
1. Candidates in DuckDB: scrobbled_at_utc within [started_at_utc - 3 min, ended_at_utc + 3 min] AND
   (artist_norm equal OR base_norm equal). Then in Python with rapidfuzz:
   artist `token_set_ratio >= 85`;
   pass 1 if `ratio(full_norm) >= 92` and scrobble within that window;
   else pass 2 if `ratio(base_norm) >= 92`, `|scrobble - start| <= 90 s` and the mix guardrail holds
   (either mix_desc is NULL or generic, or both equal).
2. Greedy 1-to-1 over all candidates sorted by is_full_listen DESC, pass ASC, |gap| ASC, score DESC
   (then sp_id, lfm_id for determinism). match_gap_sec is signed (scrobble - start).
3. events: one row per stg_spotify row (event_id = sp_id, source both/spotify) plus one per unmatched
   stg_lastfm row (event_id = 1e12 + lfm_id, source lastfm). is_skip = source 'spotify' and
   ms_played < 30000. For both rows, raw and norm strings come from Spotify, mbids from Last.fm.
4. Never loop over pairs in SQL-unfriendly ways on the full data: 245k rows must finish in under
   2 minutes. Print counts only: pass 1, pass 2, unmatched per source, Gate 1 share.

## Done when
All golden tests pass, `tests/test_match_fixture.py` passes (precision >= 0.99, recall >= 0.98 against
the fixture's links, Gate 1 >= 95%), and the full suite plus ruff are green. Then report the counts from
one run on the real data (`build_pipeline --to 02`), not rows.
