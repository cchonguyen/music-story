# W10: story chapters and charts

Tier: Sonnet (maxTurns 30). Deliverables: `sql/marts/30_labels.sql`, one loader per mart under
`site/src/data/`, chapter pages under `site/src/`, sidebar in `site/observablehq.config.js`.
Never deploy.

## Read only
`specs/W5_marts_simple.md` and `specs/W6_marts_trap.md` (table names and columns only), `site/`,
`pipeline/site_data.py`, `tests/test_site_pages.py` (acceptance; do not edit).

## Labels mart
Marts hold ids, charts need names. `sql/marts/30_labels.sql` builds `mart_artist_label(artist_id, name)`
and `mart_track_label(track_id, title, artist_id)` from dim_artist / dim_track, limited to ids that
appear in mart_artist_year or mart_track_year with rank <= 50, in mart_artist_arc with plays >= 50,
in mart_binge with rate_ratio >= 3, or in mart_remixer_year. It may read the other marts (it runs last).

## Loaders
One `site/src/data/<name>.json.sh` per `mart_<name>` table (13 from W5/W6 + 2 labels), each the same
one-liner as the existing `year.json.sh`.

## Chapters (one page each, in this sidebar order)
- `index.md` Overview (keep what is there): plays and hours per year, new artists per year.
- `artists.md` Artists: top 10 per year (year picker + table), and arcs: staples (years_active >= 10),
  comebacks (comeback_year not NULL), flashes (years_active = 1, plays >= 50), plus remixers.
- `songs.md` Songs: top tracks per year (year picker), binges (top 20 by rate_ratio with
  window_plays >= 15), song age as stacked bars per year.
- `genres.md` Genres: parent_genre share per year as a stacked area; a parent picker shows its styles.
- `habits.md` Habits: weekday x hour heatmap with a year picker, sessions per year with median and p90
  minutes, skip rate per year, platform share per year.
- `places.md` Places: plays per country per year, with 'unknown' shown separately.

Use Observable Plot and Inputs only (no extra npm packages). Captions say what a chart shows, never
claims about Charlie's life; leave a `<!-- story: ... -->` comment where narrative text will go.

## Done when
`uv run pytest tests/test_site_pages.py` passes, `cd site && npm run build` succeeds on the fixture, the
full suite and ruff are green. Report the build size.
