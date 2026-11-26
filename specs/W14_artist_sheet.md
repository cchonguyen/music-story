# W14: Artist genre sheet (export, edit outside, import back)

Charlie's answers (2026-11-26): every play; every genre with its share; CSV built in the browser.

- **Plays**: every row of `plays` (incognito included, skips excluded). Artists with `plays >= 3`.
- **Genres**: artist-level inputs as in `pipeline/genre.py` (Last.fm, Spotify 100, MusicBrainz 100, Gemini x100, Discogs 80), mapped via `genre_map` (`is_genre`), umbrellas collapsed to parent. No share floor. Shares sum to 1.
- **Artists without genres** keep one row with blank genre fields.
- **Key**: `artist_key` = `dim_artist.artist_norm` (`artist_id` shifts when artists are added).
- **CSV header**: `artist_key,artist,plays,parent_genre,style,share,source` (one row per artist per genre; `source` is `derived` or `manual`).
- **Overrides**: `DATA_DIR/artist_genre_overrides.csv` (outside the repo), copied into table `artist_genre_override` at each build.
- **Import**: validate everything first (unknown artist_key, style not in genre_map under that parent, share not positive, duplicate style, zero total). Any error writes nothing. Shares normalised to 1, rounded to 4 dp.
- **No-op rule**: genres equal to derived (within 0.0005 per share) store no override and remove any existing one.
- **Open item**: overrides do not yet change `track_genre` (Genres, Songs, Explorer keep derived values). Needs its own spec.

Slices: S1 `pipeline/artist_sheet.py` + tests. S2 site loader and browser CSV button on Artists. S3 `docs/PROJECT.md` and `STATE.md`.
Verify: `uv run pytest -q`, `uv run ruff check`, `cd site && npm run build`.
