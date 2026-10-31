-- W11/Beyond-Wrapped Insight Marts: unlocks already-collected schema columns
-- (enr_deezer_track.bpm/gain, dim_artist.lastfm_listeners/begin_year/country,
-- plays.shuffle/reason_start/completion_ratio, and post-binge survival trajectories).

-- 1. Underground Obscurity Index per year (dim_artist.lastfm_listeners)
CREATE OR REPLACE TABLE mart_obscurity_year AS
SELECT year(p.started_at_local) AS year,
       CASE
           WHEN a.lastfm_listeners IS NULL THEN 'Unranked'
           WHEN a.lastfm_listeners < 25000 THEN 'Deep Underground (<25k)'
           WHEN a.lastfm_listeners < 150000 THEN 'Indie & Niche (25k–150k)'
           WHEN a.lastfm_listeners < 750000 THEN 'Mid-Tier (150k–750k)'
           ELSE 'Global Mainstream (750k+)'
       END AS tier,
       count(*) AS plays,
       round(sum(p.ms_imputed) / 3.6e6, 2) AS listen_hours,
       count(DISTINCT p.artist_id) AS artists
FROM plays p
JOIN dim_artist a USING (artist_id)
GROUP BY 1, 2;

-- 2. Early-Adopter Vanguard Artists (first listen year vs. career begin_year)
CREATE OR REPLACE TABLE mart_vanguard AS
SELECT a.artist_id,
       a.name,
       a.begin_year,
       arc.first_year AS first_play_year,
       arc.first_year - a.begin_year AS discovery_lag_years,
       arc.plays,
       arc.years_active,
       a.lastfm_listeners,
       coalesce(a.country, 'unknown') AS country
FROM mart_artist_arc arc
JOIN dim_artist a USING (artist_id)
WHERE a.begin_year IS NOT NULL AND arc.plays >= 15
ORDER BY discovery_lag_years ASC, arc.plays DESC;

-- 3. Earworm Half-Life: Post-Binge Burnout vs. Canonized Anthems
CREATE OR REPLACE TABLE mart_earworm_halflife AS
WITH bw AS (
    SELECT b.track_id,
           b.window_start,
           b.window_plays,
           b.lifetime_plays,
           b.rate_ratio,
           count(*) FILTER (WHERE p.started_at_local::DATE < b.window_start) AS pre_plays,
           count(*) FILTER (WHERE p.started_at_local::DATE >= b.window_start + 14
                              AND p.started_at_local::DATE < b.window_start + 44) AS post_30d_plays,
           count(*) FILTER (WHERE p.started_at_local::DATE >= b.window_start + 14
                              AND p.started_at_local::DATE < b.window_start + 379) AS post_365d_plays,
           count(*) FILTER (WHERE p.started_at_local::DATE >= b.window_start + 14) AS later_plays
    FROM mart_binge b
    JOIN plays p USING (track_id)
    WHERE b.window_plays >= 15
    GROUP BY 1, 2, 3, 4, 5
)
SELECT track_id,
       window_start,
       window_plays,
       lifetime_plays,
       round(rate_ratio, 2) AS rate_ratio,
       pre_plays,
       post_30d_plays,
       post_365d_plays,
       later_plays,
       round(later_plays::DOUBLE / nullif(lifetime_plays, 0), 4) AS post_survival_share,
       CASE
           WHEN later_plays <= window_plays * 0.35 THEN 'Flash Burnout'
           WHEN later_plays >= window_plays * 1.25 THEN 'Canonized Anthem'
           ELSE 'Steady Rotation'
       END AS archetype
FROM bw;

-- 4. Intentionality vs. Algorithmic Autopilot & Skip Survival Curve
CREATE OR REPLACE TABLE mart_intent_skip AS
WITH ev AS (
    SELECT year(started_at_local) AS year,
           CASE
               WHEN coalesce(shuffle, false) THEN 'Shuffle Autopilot'
               WHEN reason_start IN ('clickrow', 'playbtn') THEN 'Hand-Picked (Click/Play)'
               ELSE 'Album / Queue Flow'
           END AS intent_mode,
           false AS is_skip,
           ms_played,
           completion_ratio
    FROM plays
    WHERE source <> 'lastfm'
    UNION ALL
    SELECT year(started_at_local) AS year,
           CASE
               WHEN coalesce(shuffle, false) THEN 'Shuffle Autopilot'
               WHEN reason_start IN ('clickrow', 'playbtn') THEN 'Hand-Picked (Click/Play)'
               ELSE 'Album / Queue Flow'
           END AS intent_mode,
           true AS is_skip,
           ms_played,
           completion_ratio
    FROM skips
    WHERE source <> 'lastfm'
)
SELECT year,
       intent_mode,
       count(*) FILTER (WHERE NOT is_skip) AS plays,
       count(*) FILTER (WHERE is_skip) AS skips,
       count(*) FILTER (WHERE is_skip AND ms_played < 5000) AS skip_under_5s,
       count(*) FILTER (WHERE is_skip AND ms_played >= 5000 AND ms_played < 15000) AS skip_5_to_15s,
       count(*) FILTER (WHERE is_skip AND ms_played >= 15000) AS skip_15_to_30s,
       round(avg(completion_ratio) FILTER (WHERE NOT is_skip), 4) AS avg_completion
FROM ev
WHERE year >= 2011
GROUP BY 1, 2;

-- 5. Circadian BPM Heartbeat & Session Energy Arc (octave-corrected Deezer BPM & gain)
CREATE OR REPLACE TABLE mart_tempo_pulse AS
WITH dz_clean AS (
    SELECT isrc,
           CASE
               WHEN bpm > 175 THEN bpm / 2.0
               WHEN bpm > 0 AND bpm < 55 THEN bpm * 2.0
               ELSE bpm
           END AS bpm_clean,
           gain
    FROM enr_deezer_track
    WHERE http_status = 200 AND bpm IS NOT NULL AND bpm > 0
),
tagged_plays AS (
    SELECT hour(p.started_at_local) AS hr,
           least(p.session_index, 15) AS s_idx,
           year(p.started_at_local) AS yr,
           dz.bpm_clean,
           dz.gain
    FROM plays p
    JOIN dim_track t USING (track_id)
    JOIN dz_clean dz ON dz.isrc = t.isrc
)
SELECT 'hour' AS bucket_type,
       hr AS bucket,
       count(*) AS plays,
       round(avg(bpm_clean), 2) AS avg_bpm,
       round(quantile_cont(bpm_clean, 0.25), 2) AS p25_bpm,
       round(quantile_cont(bpm_clean, 0.75), 2) AS p75_bpm,
       round(avg(gain), 2) AS avg_gain
FROM tagged_plays GROUP BY 1, 2
UNION ALL
SELECT 'session_index' AS bucket_type,
       s_idx AS bucket,
       count(*) AS plays,
       round(avg(bpm_clean), 2) AS avg_bpm,
       round(quantile_cont(bpm_clean, 0.25), 2) AS p25_bpm,
       round(quantile_cont(bpm_clean, 0.75), 2) AS p75_bpm,
       round(avg(gain), 2) AS avg_gain
FROM tagged_plays GROUP BY 1, 2
UNION ALL
SELECT 'year' AS bucket_type,
       yr AS bucket,
       count(*) AS plays,
       round(avg(bpm_clean), 2) AS avg_bpm,
       round(quantile_cont(bpm_clean, 0.25), 2) AS p25_bpm,
       round(quantile_cont(bpm_clean, 0.75), 2) AS p75_bpm,
       round(avg(gain), 2) AS avg_gain
FROM tagged_plays GROUP BY 1, 2;

-- 6. Musical Passport: Listener Location vs. Artist Origin Country
CREATE OR REPLACE TABLE mart_artist_passport AS
SELECT year(p.started_at_local) AS year,
       coalesce(p.country, 'unknown') AS listener_country,
       coalesce(a.country, 'unknown') AS artist_country,
       count(*) AS plays,
       count(DISTINCT p.artist_id) AS artists
FROM plays p
JOIN dim_artist a USING (artist_id)
GROUP BY 1, 2, 3;

-- 7. W9c Track Genre Lineage X-Ray (uniquely keyed on 4-tuple: artist_norm, title_norm, parent_genre, style)
CREATE OR REPLACE TABLE mart_genre_xray AS
WITH top_genre AS (
    SELECT track_id, parent_genre, style, weight, level
    FROM track_genre
    QUALIFY row_number() OVER (PARTITION BY track_id ORDER BY weight DESC, parent_genre, style) = 1
),
sec_genre AS (
    SELECT g.track_id,
           string_agg(
               g.style || ' (' || round(g.weight * 100, 0)::INT::VARCHAR || '%)',
               ', ' ORDER BY g.weight DESC, g.style
           ) AS secondary_styles
    FROM track_genre g
    JOIN top_genre tg
      ON tg.track_id = g.track_id
     AND NOT (tg.parent_genre = g.parent_genre AND tg.style = g.style)
    GROUP BY 1
),
track_artist_pairs AS (
    SELECT DISTINCT track_id, artist_id FROM plays
    UNION
    SELECT DISTINCT track_id, artist_id FROM skips
    UNION
    SELECT track_id, primary_artist_id AS artist_id FROM dim_track
),
play_stats AS (
    SELECT track_id,
           artist_id,
           count(*) AS plays,
           sum(ms_imputed) AS ms_imputed,
           min(year(started_at_local)) AS first_year,
           max(year(started_at_local)) AS last_year
    FROM plays
    GROUP BY 1, 2
),
skip_stats AS (
    SELECT track_id,
           artist_id,
           count(*) AS skips
    FROM skips
    GROUP BY 1, 2
),
pair_keys AS (
    SELECT tap.track_id,
           tap.artist_id,
           a.name AS artist,
           t.title,
           a.artist_norm,
           t.full_norm AS title_norm,
           tg.parent_genre,
           tg.style,
           tg.weight,
           tg.level,
           coalesce(sg.secondary_styles, '') AS secondary_styles,
           coalesce(ps.plays, 0) AS plays,
           coalesce(ps.ms_imputed, 0) AS ms_imputed,
           coalesce(ss.skips, 0) AS skips,
           ps.first_year,
           ps.last_year
    FROM track_artist_pairs tap
    JOIN dim_artist a USING (artist_id)
    JOIN dim_track t USING (track_id)
    JOIN top_genre tg USING (track_id)
    LEFT JOIN sec_genre sg USING (track_id)
    LEFT JOIN play_stats ps USING (track_id, artist_id)
    LEFT JOIN skip_stats ss USING (track_id, artist_id)
),
hr_counts AS (
    SELECT pk.artist_norm,
           pk.title_norm,
           pk.parent_genre,
           pk.style,
           hour(p.started_at_local) AS hr,
           count(*) AS n
    FROM plays p
    JOIN pair_keys pk USING (track_id, artist_id)
    GROUP BY 1, 2, 3, 4, 5
),
peak_hr AS (
    SELECT artist_norm,
           title_norm,
           parent_genre,
           style,
           hr AS peak_local_hour
    FROM hr_counts
    QUALIFY row_number() OVER (
        PARTITION BY artist_norm, title_norm, parent_genre, style
        ORDER BY n DESC, hr ASC
    ) = 1
),
country_counts AS (
    SELECT pk.artist_norm,
           pk.title_norm,
           pk.parent_genre,
           pk.style,
           coalesce(p.country, 'US') AS country,
           count(*) AS n
    FROM plays p
    JOIN pair_keys pk USING (track_id, artist_id)
    GROUP BY 1, 2, 3, 4, 5
),
modal_country AS (
    SELECT artist_norm,
           title_norm,
           parent_genre,
           style,
           country AS top_country
    FROM country_counts
    QUALIFY row_number() OVER (
        PARTITION BY artist_norm, title_norm, parent_genre, style
        ORDER BY n DESC, country ASC
    ) = 1
),
grouped AS (
    SELECT pk.artist_norm,
           pk.title_norm,
           pk.parent_genre,
           pk.style,
           arg_max(pk.track_id, pk.plays * 1000000 - coalesce(length(pk.track_id), 0)) AS track_id,
           arg_max(pk.title, pk.plays) AS title,
           arg_max(pk.artist, pk.plays) AS artist,
           round(
               coalesce(
                   sum(pk.weight * pk.plays) / nullif(sum(pk.plays), 0),
                   avg(pk.weight)
               ),
               4
           ) AS primary_weight,
           arg_max(pk.level, pk.plays) AS level,
           arg_max(pk.secondary_styles, pk.plays) AS secondary_styles,
           CASE
               WHEN pk.style <> pk.parent_genre THEN 'disaggregated -> ' || pk.style
               ELSE 'umbrella retained (' || pk.parent_genre || ')'
           END AS suppressed_umbrellas,
           sum(pk.plays)::BIGINT AS plays,
           round(sum(pk.ms_imputed) / 3.6e6, 2) AS listen_hours,
           round(
               sum(pk.skips)::DOUBLE / nullif(sum(pk.plays) + sum(pk.skips), 0),
               4
           ) AS skip_rate,
           min(pk.first_year) AS first_year,
           max(pk.last_year) AS last_year
    FROM pair_keys pk
    GROUP BY 1, 2, 3, 4
)
SELECT g.track_id,
       g.title,
       g.artist,
       g.artist_norm,
       g.title_norm,
       g.parent_genre,
       g.style,
       g.primary_weight,
       g.level,
       g.secondary_styles,
       g.suppressed_umbrellas,
       g.plays,
       g.listen_hours,
       coalesce(g.skip_rate, 0.0) AS skip_rate,
       coalesce(ph.peak_local_hour, 12) AS peak_local_hour,
       coalesce(mc.top_country, 'US') AS top_country,
       coalesce(g.first_year, 2020) AS first_year,
       coalesce(g.last_year, 2026) AS last_year
FROM grouped g
LEFT JOIN peak_hr ph USING (artist_norm, title_norm, parent_genre, style)
LEFT JOIN modal_country mc USING (artist_norm, title_norm, parent_genre, style);

-- 8. W9c Genre -> Sub-Style -> Artist Hierarchy Breakdown
CREATE OR REPLACE TABLE mart_genre_hierarchy AS
WITH style_artist AS (
    SELECT g.parent_genre,
           g.style,
           p.artist_id,
           a.name AS artist,
           count(*) AS plays,
           sum(g.weight) AS plays_weighted,
           sum(p.ms_imputed) / 3.6e6 AS listen_hours,
           count(DISTINCT p.track_id) AS tracks
    FROM plays p
    JOIN track_genre g USING (track_id)
    JOIN dim_artist a USING (artist_id)
    GROUP BY 1, 2, 3, 4
),
totals AS (
    SELECT *,
           sum(plays_weighted) OVER (PARTITION BY parent_genre, style) AS style_weighted,
           sum(plays_weighted) OVER (PARTITION BY parent_genre) AS parent_weighted,
           row_number() OVER (
               PARTITION BY parent_genre, style
               ORDER BY plays_weighted DESC, plays DESC, artist_id ASC
           ) AS artist_rank_in_style
    FROM style_artist
)
SELECT parent_genre,
       style,
       artist_id,
       artist,
       plays,
       round(plays_weighted, 2) AS plays_weighted,
       round(listen_hours, 2) AS listen_hours,
       tracks,
       round(style_weighted / nullif(parent_weighted, 0), 4) AS style_share_of_parent,
       round(plays_weighted / nullif(style_weighted, 0), 4) AS artist_share_of_style,
       artist_rank_in_style
FROM totals
WHERE artist_rank_in_style <= 15;

-- 9. W9c Local-Time Circadian Genre Clock (uses plays.started_at_local)
CREATE OR REPLACE TABLE mart_genre_clock AS
WITH base AS (
    SELECT g.parent_genre,
           g.style,
           CASE
               WHEN isodow(p.started_at_local) IN (6, 7) THEN 'weekend'
               ELSE 'weekday'
           END AS weekday_type,
           hour(p.started_at_local) AS hour,
           count(*) AS plays,
           sum(g.weight) AS plays_weighted,
           sum(p.ms_imputed) / 3.6e6 AS listen_hours
    FROM plays p
    JOIN track_genre g USING (track_id)
    GROUP BY 1, 2, 3, 4
)
SELECT parent_genre,
       style,
       weekday_type,
       hour,
       plays,
       round(plays_weighted, 2) AS plays_weighted,
       round(listen_hours, 2) AS listen_hours
FROM base
UNION ALL
SELECT parent_genre,
       style,
       'all' AS weekday_type,
       hour,
       sum(plays)::BIGINT AS plays,
       round(sum(plays_weighted), 2) AS plays_weighted,
       round(sum(listen_hours), 2) AS listen_hours
FROM base
GROUP BY 1, 2, 3, 4;
