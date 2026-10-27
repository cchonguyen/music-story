-- One row per play or skip with names instead of ids, for the site's DuckDB-Wasm explorer.
-- A view, not a mart table: pipeline.site_data writes it to one Zstd Parquet file, sorted for compression.
-- is_skip marks rows from `skips`; the explorer leaves them out unless asked, so its play counts match the
-- marts. Genre is the track's heaviest (parent_genre, style); tracks with no genre row get NULL.
CREATE OR REPLACE VIEW explorer_plays AS
WITH top_genre AS (
    SELECT track_id, parent_genre, style
    FROM track_genre
    QUALIFY row_number() OVER (PARTITION BY track_id ORDER BY weight DESC, parent_genre, style) = 1
), events AS (
    SELECT started_at_local, track_id, artist_id, album_id, ms_imputed, platform_family, country, source,
           false AS is_skip
    FROM plays
    UNION ALL
    SELECT started_at_local, track_id, artist_id, album_id, ms_imputed, platform_family, country, source,
           true AS is_skip
    FROM skips
)
SELECT e.started_at_local AS ts,
       a.name AS artist,
       t.title,
       al.name AS album,
       a.artist_norm,
       t.full_norm AS title_norm,
       g.parent_genre,
       g.style,
       CAST(e.ms_imputed / 60000.0 AS FLOAT) AS minutes,
       e.is_skip,
       e.platform_family AS platform,
       e.country,
       e.source
FROM events e
JOIN dim_artist a USING (artist_id)
JOIN dim_track t USING (track_id)
LEFT JOIN dim_album al ON al.album_id = e.album_id
LEFT JOIN top_genre g USING (track_id);
