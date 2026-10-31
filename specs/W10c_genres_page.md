# W10c — Genres Page Upgrade: Hierarchy, Circadian Rhythm & Song Genre X-Ray

## Goal
Upgrade `site/src/genres.md` to surface the two-tier `W9b` genre taxonomy, `mart_genre_hierarchy`, `mart_genre_clock`, and `mart_genre_xray` while preserving all existing W10 charts and `<!-- story: genres -->` comments.

## Sections & Interactive Components
1. **Share of Plays by Parent Genre + Synchronized Summary Table (`genre_year.json`, `year.json`)**
   - Preserves the Epistemic Coverage Toggle (`Classified Genres Only (100% Share)`, `Share of All Plays (Include Unclassified Band)`, `Weighted Play Counts`) and stacked area chart.
   - Adds a synchronized `Inputs.table` summarizing each parent genre's cumulative weighted plays, share of classified plays, share of total plays, distinct sub-styles, and peak year.
2. **Styles Within a Parent Genre + Synchronized Sub-Style Table (`genre_year.json`)**
   - Preserves the parent genre picker and `Weighted Plays` / `100% Share within Parent Genre` toggle and area chart.
   - Adds a synchronized `Inputs.table` ranking every sub-style within the chosen parent genre (`style`, `plays_weighted`, `share_of_parent`, `umbrella_status`, `first_year`, `peak_year`).
3. **Genre $\to$ Sub-Style $\to$ Artist Hierarchy Breakdown (`genre_hierarchy.json`)**
   - Interactive parent genre & sub-style filter controls.
   - `Plot.barX` chart of top artists within the selected parent genre / sub-style.
   - Synchronized `Inputs.table` (`parent_genre`, `style`, `artist`, `plays`, `plays_weighted`, `listen_hours`, `tracks`, `style_share_of_parent`, `artist_share_of_style`).
4. **Local-Time Circadian Rhythm by Genre (`genre_clock.json`)**
   - Interactive filters for `weekday_type` (`all`, `weekday`, `weekend`), dimension (`Parent Genres` vs. `Sub-Styles in Selected Parent`), and normalization (`Row-Normalized % of Genre` vs. `Weighted Plays`).
   - `Plot.cell` 24-hour (`0..23` `started_at_local`) heatmap and synchronized `Inputs.table` with daypart shares (`Night 00–05`, `Morning 06–11`, `Afternoon 12–17`, `Evening 18–23`) and modal peak hour.
5. **Song Genre X-Ray & Umbrella Disaggregation Inspector (`genre_xray.json`)**
   - Interactive search (`title` / `artist`), Parent Genre select, Sub-Style select, Tag Level select (`All`, `track`, `album`, `artist`), and Umbrella Status select (`All`, `Disaggregated to Specific Style`, `Umbrella Retained`).
   - Synchronized `Inputs.table` showing `title`, `artist`, `parent_genre`, `style`, `primary_weight`, `level`, `secondary_styles`, `suppressed_umbrellas`, `plays`, `listen_hours`, `skip_rate`, `peak_local_hour`, `top_country`, `first_year`, `last_year`.
