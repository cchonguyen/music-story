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

-- 7. Explorer events table for instant zero-CDN fallback and in-browser Remix Studio slicing
CREATE OR REPLACE TABLE mart_explorer_events AS
SELECT * FROM explorer_plays;
