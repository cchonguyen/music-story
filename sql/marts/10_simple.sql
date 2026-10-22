-- W5: simple marts. Inputs: plays, skips, sessions, dim_track, track_genre.
-- Every table is CREATE OR REPLACE, so this file is re-runnable.
-- year and weekday/hour use local time (started_at_local). Hours = ms_imputed / 3.6e6.

CREATE OR REPLACE TABLE mart_year AS
WITH first_a AS (
    SELECT artist_id, arg_min(year(started_at_local), started_at_utc) AS y FROM plays GROUP BY 1
),
first_t AS (
    SELECT track_id, arg_min(year(started_at_local), started_at_utc) AS y FROM plays GROUP BY 1
),
p AS (
    SELECT year(started_at_local) AS year,
           count(*) AS plays,
           sum(ms_imputed) / 3.6e6 AS listen_hours,
           count(DISTINCT artist_id) AS artists,
           count(DISTINCT track_id) AS tracks
    FROM plays GROUP BY 1
)
SELECT p.year,
       p.plays,
       coalesce(s.skips, 0) AS skips,
       p.listen_hours,
       p.artists,
       p.tracks,
       coalesce(na.n, 0) AS new_artists,
       coalesce(nt.n, 0) AS new_tracks,
       coalesce(se.n, 0) AS sessions
FROM p
LEFT JOIN (SELECT year(started_at_local) AS y, count(*) AS skips FROM skips GROUP BY 1) s ON s.y = p.year
LEFT JOIN (SELECT y, count(*) AS n FROM first_a GROUP BY 1) na ON na.y = p.year
LEFT JOIN (SELECT y, count(*) AS n FROM first_t GROUP BY 1) nt ON nt.y = p.year
LEFT JOIN (SELECT year(started_at_local) AS y, count(*) AS n FROM sessions GROUP BY 1) se ON se.y = p.year;

CREATE OR REPLACE TABLE mart_artist_year AS
WITH a AS (
    SELECT year(started_at_local) AS year, artist_id,
           count(*) AS plays,
           sum(ms_imputed) / 3.6e6 AS listen_hours,
           sum(ms_imputed) AS ms
    FROM plays GROUP BY 1, 2
)
SELECT year, artist_id, plays, listen_hours,
       row_number() OVER (PARTITION BY year ORDER BY plays DESC, ms DESC, artist_id) AS rank
FROM a;

CREATE OR REPLACE TABLE mart_track_year AS
WITH t AS (
    SELECT year(p.started_at_local) AS year, p.track_id,
           any_value(d.primary_artist_id) AS artist_id,
           count(*) AS plays,
           sum(p.ms_imputed) / 3.6e6 AS listen_hours,
           sum(p.ms_imputed) AS ms
    FROM plays p JOIN dim_track d USING (track_id)
    GROUP BY 1, 2
)
SELECT year, track_id, artist_id, plays, listen_hours,
       row_number() OVER (PARTITION BY year ORDER BY plays DESC, ms DESC, track_id) AS rank
FROM t;

CREATE OR REPLACE TABLE mart_clock AS
SELECT year(started_at_local) AS year,
       isodow(started_at_local) AS weekday,
       hour(started_at_local) AS hour,
       count(*) AS plays
FROM plays
GROUP BY 1, 2, 3;

CREATE OR REPLACE TABLE mart_genre_year AS
SELECT year(p.started_at_local) AS year,
       g.parent_genre,
       g.style,
       sum(g.weight) AS plays_weighted
FROM plays p JOIN track_genre g USING (track_id)
GROUP BY 1, 2, 3;

CREATE OR REPLACE TABLE mart_platform_year AS
SELECT year(started_at_local) AS year,
       coalesce(platform_family, 'unknown') AS platform_family,
       count(*) AS plays
FROM plays
GROUP BY 1, 2;
