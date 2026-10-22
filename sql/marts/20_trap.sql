-- W6 trap marts. Inputs: plays, skips, sessions, dim_track, bridge_track_artist.
-- Each mart avoids a tempting wrong answer; see specs/W6_marts_trap.md.

-- 1. Artist arc: active years are counted, not last_year - first_year.
CREATE OR REPLACE TABLE mart_artist_arc AS
WITH ay AS (
    SELECT artist_id, year(started_at_local) AS year, count(*) AS n
    FROM plays GROUP BY 1, 2
), gaps AS (
    SELECT artist_id, year, n,
           coalesce(year - lag(year) OVER (PARTITION BY artist_id ORDER BY year) - 1, 0) AS gap
    FROM ay
)
SELECT artist_id,
       sum(n)::BIGINT AS plays,
       min(year) AS first_year,
       max(year) AS last_year,
       count(*) AS years_active,
       max(gap) AS longest_gap_years,
       min(year) FILTER (WHERE gap >= 3) AS comeback_year,
       arg_min(year, (-n, year)) AS peak_year,
       max(n) / sum(n) AS peak_share
FROM gaps
GROUP BY artist_id;

-- 2. Binge: rolling 14 local-day windows starting on any play day, not calendar buckets.
CREATE OR REPLACE TABLE mart_binge AS
WITH d AS (
    SELECT track_id, started_at_local::DATE AS day
    FROM plays
    WHERE track_id IN (SELECT track_id FROM plays GROUP BY 1 HAVING count(*) >= 10)
), life AS (
    SELECT track_id, count(*) AS lifetime_plays,
           greatest(14, max(day) - min(day) + 1) AS span_days
    FROM d GROUP BY 1
), w AS (
    SELECT a.track_id, a.day AS window_start, count(*) AS n
    FROM (SELECT DISTINCT track_id, day FROM d) a
    JOIN d b ON b.track_id = a.track_id AND b.day >= a.day AND b.day < a.day + 14
    GROUP BY 1, 2
), best AS (
    SELECT track_id, arg_min(window_start, (-n, window_start)) AS window_start, max(n) AS window_plays
    FROM w GROUP BY 1
)
SELECT b.track_id, b.window_start, b.window_plays, l.lifetime_plays,
       b.window_plays / (l.lifetime_plays * 14.0 / l.span_days) AS rate_ratio
FROM best b JOIN life l USING (track_id);

-- 3. Remixer year: credit via bridge_track_artist role 'remixer', not primary artist.
CREATE OR REPLACE TABLE mart_remixer_year AS
WITH rx AS (
    SELECT DISTINCT b.artist_id, b.track_id, t.work_id
    FROM bridge_track_artist b JOIN dim_track t USING (track_id)
    WHERE b.role = 'remixer'
), remix AS (
    SELECT r.artist_id, year(p.started_at_local) AS year, count(*) AS n
    FROM (SELECT DISTINCT artist_id, track_id FROM rx) r
    JOIN plays p USING (track_id)
    GROUP BY 1, 2
), orig_tracks AS (
    SELECT DISTINCT r.artist_id, t.track_id
    FROM (SELECT DISTINCT artist_id, work_id FROM rx) r
    JOIN dim_track t ON t.work_id = r.work_id AND NOT t.is_remix
), orig AS (
    SELECT o.artist_id, year(p.started_at_local) AS year, count(*) AS n
    FROM orig_tracks o JOIN plays p USING (track_id)
    GROUP BY 1, 2
)
SELECT artist_id, year,
       coalesce(remix.n, 0) AS remix_plays,
       coalesce(orig.n, 0) AS original_plays
FROM remix FULL OUTER JOIN orig USING (artist_id, year)
WHERE coalesce(remix.n, 0) > 0 OR coalesce(orig.n, 0) > 0;

-- 4. Song age: work_year (the composition), not recording_year (a remaster looks new).
CREATE OR REPLACE TABLE mart_song_age AS
WITH p AS (
    SELECT year(p.started_at_local) AS year, year(p.started_at_local) - t.work_year AS age, t.work_year
    FROM plays p JOIN dim_track t USING (track_id)
)
SELECT year,
       CASE WHEN work_year IS NULL THEN 'unknown'
            WHEN age <= 0 THEN '0'
            WHEN age <= 2 THEN '1-2'
            WHEN age <= 5 THEN '3-5'
            WHEN age <= 10 THEN '6-10'
            WHEN age <= 20 THEN '11-20'
            ELSE '21+' END AS age_bucket,
       count(*) AS plays
FROM p
GROUP BY 1, 2;

-- 5. Skip rate: Last.fm-only plays cannot be skips, so they stay out of the denominator.
CREATE OR REPLACE TABLE mart_skip_rate AS
WITH sp AS (
    SELECT year(started_at_local) AS year, count(*) AS n
    FROM plays WHERE source <> 'lastfm' GROUP BY 1
), sk AS (
    SELECT year(started_at_local) AS year, count(*) AS n
    FROM skips GROUP BY 1
)
SELECT sp.year,
       coalesce(sk.n, 0) AS skips,
       sp.n AS spotify_plays,
       coalesce(sk.n, 0) / (coalesce(sk.n, 0) + sp.n) AS skip_rate
FROM sp LEFT JOIN sk USING (year)
WHERE sp.year >= 2012;

-- 6. Sessions per year: durations from UTC timestamps (local times jump at DST).
CREATE OR REPLACE TABLE mart_sessions_year AS
WITH s AS (
    SELECT year(started_at_local) AS year,
           count(*) AS sessions,
           median(epoch(ended_at_utc - started_at_utc) / 60) AS median_minutes,
           quantile_cont(epoch(ended_at_utc - started_at_utc) / 60, 0.9) AS p90_minutes
    FROM sessions GROUP BY 1
), f AS (
    SELECT year,
           sum(new_session_10::INT)::BIGINT AS sessions_10,
           sum(new_session_30::INT)::BIGINT AS sessions_30
    FROM (SELECT year(started_at_local) AS year, new_session_10, new_session_30 FROM plays
          UNION ALL
          SELECT year(started_at_local), new_session_10, new_session_30 FROM skips)
    GROUP BY 1
)
SELECT s.year, s.sessions, s.median_minutes, s.p90_minutes,
       coalesce(f.sessions_10, 0) AS sessions_10,
       coalesce(f.sessions_30, 0) AS sessions_30
FROM s LEFT JOIN f USING (year);

-- 7. Country per year: NULL country is 'unknown'.
CREATE OR REPLACE TABLE mart_country_year AS
SELECT year(started_at_local) AS year,
       coalesce(country, 'unknown') AS country,
       count(*) AS plays,
       count(*) FILTER (WHERE country_imputed) AS imputed_plays
FROM plays
GROUP BY 1, 2;
