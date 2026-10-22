# W9: genre taxonomy

Tier: Sonnet (maxTurns 30). Deliverables: `data/genre_map.csv`, `pipeline/genre.py` with `run(con)`
(build step 06) and a curation CLI.

## Read only
`sql/schema.sql` Layers 4, 5 and 7, `pipeline/config.py`, `tests/test_genre_fixture.py` (acceptance; do not
edit), `tests/helpers.py`.

## data/genre_map.csv
Header `tag,style,parent_genre,is_genre`. Lower-case trimmed tags. A starter map of at least 120 rows:
the common Last.fm / Spotify / MusicBrainz genre tags (e.g. house, deep house, tech house, techno,
dubstep, drum and bass, ambient, indie rock, indie pop, k-pop, v-pop, j-pop, hip hop, rap, trap, r&b,
soul, jazz, classical, folk, metal, punk, country, latin, reggaeton, soundtrack...) plus common noise
tags with is_genre false (seen live, favorites, favourite, love, awesome, female vocalists, male
vocalists, british, american, under 2000 listeners...). Parent genres come from this closed list:
electronic, rock, pop, hip hop, r&b, jazz, classical, folk, metal, country, latin, world, soundtrack.
k-pop / v-pop / j-pop are styles of pop; ambient, house, techno, dubstep, electro house are styles of
electronic; indie rock of rock. When a style has no finer split, style = the tag.

## Rules for run(con)
1. Delete and reload `genre_map` from the CSV, then add (when absent) every year 1900-2099 ('1997'),
   decade ('1990s') and short decade ('90s') as is_genre false. Tags not in the map are ignored.
2. Tags per level for each dim_track row, keeping only is_genre tags:
   track = Last.fm track tags (`artist_norm::full_norm`, their count) + MB recording genres (count 100
   each, by the track's ISRC or MBID); album = Last.fm album tags (`artist_norm::album_norm` of the
   track's album); artist = Last.fm artist tags + Spotify artist genres + MB artist genres (100 each)
   of the primary artist.
3. Within a level, a style's weight = its count / the level's total count. Combine: 1.0 x track +
   0.7 x album + 0.5 x artist. Drop styles below 15% of the track's total, renormalise so weights sum
   to 1. level = the first of track, album, artist that contributed a kept style. Tracks with no genre
   tag at any level get no rows.
4. `uv run python -m pipeline.genre unmapped [--top N]` reads MUSIC_DB and prints the N (default 50)
   unmapped tags with the most plays behind them, one `plays<TAB>tag` per line, for curation.

## Done when
`uv run pytest tests/test_genre_fixture.py` passes; full suite and ruff green. Report the CSV row count
and the share of fixture tracks with a genre.
