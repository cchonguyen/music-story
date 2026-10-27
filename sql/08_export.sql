-- 08_export.sql (W12): export_plays, the row-level plays the explorer page ships.
-- Privacy gate: no incognito plays, no timestamps (local date, hour, weekday only),
-- no ids that encode order, no raw platform strings. See specs/W12_export.md.
-- Inputs: plays, dim_track, dim_artist, dim_album, track_genre. Re-runnable.

CREATE OR REPLACE TABLE export_plays AS
WITH genre AS (
    SELECT track_id, arg_max(parent_genre, (weight, parent_genre, style)) AS parent_genre,
           arg_max(style, (weight, parent_genre, style)) AS style
    FROM track_genre GROUP BY 1
)
SELECT CAST(p.started_at_local AS DATE)             AS local_date,
       CAST(year(p.started_at_local) AS SMALLINT)   AS year,
       CAST(hour(p.started_at_local) AS TINYINT)    AS hour,
       CAST(isodow(p.started_at_local) AS TINYINT)  AS weekday,
       a.name                                       AS artist,
       t.title                                      AS track,
       al.name                                      AS album,
       g.parent_genre,
       g.style,
       CAST(t.recording_year AS SMALLINT)           AS release_year,
       CAST(round(p.ms_imputed / 1000) AS INTEGER)  AS seconds,
       p.source,
       p.platform_family                            AS platform,
       p.country,
       p.shuffle
FROM plays p
JOIN dim_track t ON t.track_id = p.track_id
JOIN dim_artist a ON a.artist_id = p.artist_id
LEFT JOIN dim_album al ON al.album_id = p.album_id
LEFT JOIN genre g ON g.track_id = p.track_id
WHERE NOT coalesce(p.incognito, false)
ORDER BY year, artist, track, local_date, hour;
