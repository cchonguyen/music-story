# W15: Track genre sheet (export and import)

Status: draft, approved in principle by Charlie on 2026-11-26. Not built.

## Goal
Charlie exports one row per track, with title, artist and current genres, gives it to an AI agent to fill in genres, and imports the edited file. Imported track genres replace the automatic genres for those tracks.

## Decisions (from Charlie, 2026-11-26)
- Scope: tracks with 3 or more plays.
- Import fully replaces the automatic genre for each track it lists. Tracks not in the file keep their automatic genre.
- An artist's genre edits (the W14 artist sheet) carry down to that artist's tracks that have no track-level edit.
- Saved edits survive every rebuild.

## Precedence (per track)
1. Track edit from the track sheet (replaces everything below for that track).
2. Artist edit from the artist sheet, applied to each track of that artist.
3. Automatic genre from `pipeline/genre.py` (step 06).

## Data
- Track key: `track_id` (the key `track_genre` uses). The export also includes `artist` and `title` so the agent can look tracks up.
- Import file: `DATA_DIR/track_genre_overrides.csv`, loaded into table `track_genre_override`, same pattern as `artist_genre_override` in `pipeline/artist_sheet.py`.
- Columns: `track_id,title,artist,plays,parent_genre,style,share,source`. One row per track and genre, with shares summing to 1 per track, as in the artist sheet.

## Where it hooks in
- Step 06 (`pipeline/genre.py`) builds `track_genre`. The track override and artist override are applied after step 06 in a new step, so `track_genre` always reflects them. Step 07 (marts) and the site then pick them up.
- Open point for the first slice: `track_genre` is the rebuilt table. The override step must run after step 06 on every build, and must fail loudly if a track in the file no longer exists.

## Validation on import (same rules as the artist sheet)
- Parent genre and style must exist in the genre map.
- Shares per track must sum to 1 within tolerance.
- Unknown track_id is an error, not a silent skip.
- Dry run first, as `import <path> --dry-run`.

## Out of scope
- Changing how automatic genres are derived.
- Tracks with fewer than 3 plays.
