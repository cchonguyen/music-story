-- Names for the ids the charts show. Runs last; reads other marts.
CREATE OR REPLACE TABLE mart_track_label AS
SELECT t.track_id, t.title, t.primary_artist_id AS artist_id
FROM dim_track t
WHERE t.track_id IN (SELECT track_id FROM mart_track_year WHERE rank <= 50)
   OR t.track_id IN (SELECT track_id FROM mart_binge WHERE rate_ratio >= 3);

CREATE OR REPLACE TABLE mart_artist_label AS
SELECT a.artist_id, a.name
FROM dim_artist a
WHERE a.artist_id IN (SELECT artist_id FROM mart_artist_year WHERE rank <= 50)
   OR a.artist_id IN (SELECT artist_id FROM mart_track_year WHERE rank <= 50)
   OR a.artist_id IN (SELECT artist_id FROM mart_artist_arc WHERE plays >= 50)
   OR a.artist_id IN (SELECT artist_id FROM mart_remixer_year)
   OR a.artist_id IN (SELECT artist_id FROM mart_track_label);
