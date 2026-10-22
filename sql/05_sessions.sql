-- 05_sessions.sql (W8): plays, skips and sessions from events + staging + dimensions.
-- Input variable: getvariable('country_tz_csv'). Re-runnable.

DELETE FROM plays;
DELETE FROM skips;
DELETE FROM sessions;

-- 1. track resolution, spotify-side columns, end time
CREATE OR REPLACE TEMP TABLE w8_base AS
SELECT e.event_id, e.source, e.is_skip, e.started_at_utc, e.ms_played, e.match_pass, e.match_gap_sec,
       e.sp_id, coalesce(um.track_id, km.track_id) AS track_id,
       dt.primary_artist_id AS artist_id,
       coalesce(da.album_id, dt.album_id) AS album_id,
       dt.duration_ms, coalesce(dt.is_longform_mix, false) AS is_longform_mix,
       coalesce(e.ended_at_utc,
                e.started_at_utc + to_milliseconds(coalesce(dt.duration_ms, 210000))) AS ended_at_utc,
       CASE WHEN s.sp_id IS NULL THEN NULL
            WHEN s.country_raw IS NULL OR s.country_raw = 'ZZ' THEN NULL
            ELSE s.country_raw END AS known_country,
       s.platform_family, s.shuffle, s.offline, s.incognito, s.reason_start, s.reason_end, s.skipped
FROM events e
LEFT JOIN stg_spotify s ON s.sp_id = e.sp_id
LEFT JOIN track_uri_map um ON um.track_uri = e.track_uri
LEFT JOIN track_key_map km ON km.artist_norm = e.artist_norm AND km.full_norm = e.full_norm
LEFT JOIN dim_track dt ON dt.track_id = coalesce(um.track_id, km.track_id)
LEFT JOIN enr_spotify_track et ON et.track_uri = e.track_uri
LEFT JOIN dim_album da ON da.spotify_album_id = et.album_spotify_id;

-- 3. country imputation over Spotify-backed rows
CREATE OR REPLACE TEMP TABLE w8_country AS
WITH sp AS (
    SELECT event_id, started_at_utc, known_country,
           last_value(known_country IGNORE NULLS) OVER prev AS prev_c,
           last_value(CASE WHEN known_country IS NOT NULL THEN started_at_utc END IGNORE NULLS) OVER prev AS prev_t,
           first_value(known_country IGNORE NULLS) OVER nxt AS next_c,
           first_value(CASE WHEN known_country IS NOT NULL THEN started_at_utc END IGNORE NULLS) OVER nxt AS next_t
    FROM w8_base WHERE sp_id IS NOT NULL
    WINDOW prev AS (ORDER BY started_at_utc, event_id ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW),
           nxt AS (ORDER BY started_at_utc, event_id ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING)
)
SELECT event_id,
       CASE WHEN known_country IS NOT NULL THEN known_country
            WHEN prev_c = next_c AND started_at_utc - prev_t <= INTERVAL 48 HOUR
                 AND next_t - started_at_utc <= INTERVAL 48 HOUR THEN prev_c END AS country,
       known_country IS NULL AND prev_c = next_c AND started_at_utc - prev_t <= INTERVAL 48 HOUR
                 AND next_t - started_at_utc <= INTERVAL 48 HOUR AS country_imputed
FROM sp;

-- 4. time zone
CREATE OR REPLACE TEMP TABLE w8_tz AS
SELECT * FROM read_csv(getvariable('country_tz_csv'), header = true, all_varchar = true);

-- 5. sessions over all rows
CREATE OR REPLACE TEMP TABLE w8_rows AS
WITH j AS (
    SELECT b.*, c.country, coalesce(c.country_imputed, false) AS country_imputed,
           coalesce(z.tz, (SELECT tz FROM w8_tz WHERE country = 'US')) AS tz
    FROM w8_base b
    LEFT JOIN w8_country c USING (event_id)
    LEFT JOIN w8_tz z ON z.country = coalesce(c.country, 'US')
), g AS (
    SELECT *, started_at_utc - max(ended_at_utc) OVER (ORDER BY started_at_utc, event_id
                                  ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS gap
    FROM j
), f AS (
    SELECT *, gap IS NULL OR gap > INTERVAL 20 MINUTE AS new_s,
           gap IS NULL OR gap > INTERVAL 10 MINUTE AS new_session_10,
           gap IS NULL OR gap > INTERVAL 30 MINUTE AS new_session_30
    FROM g
), s AS (
    SELECT *, sum(new_s::INT) OVER (ORDER BY started_at_utc, event_id) AS session_id FROM f
)
SELECT *, row_number() OVER (PARTITION BY session_id ORDER BY started_at_utc, event_id) AS session_index,
       row_number() OVER (ORDER BY started_at_utc, event_id) AS rn
FROM s;

-- 6. median completion and the final fact rows
CREATE OR REPLACE TEMP TABLE w8_facts AS
WITH med AS (
    SELECT median(ms_played / duration_ms) AS m FROM w8_rows
    WHERE sp_id IS NOT NULL AND ms_played >= 30000 AND duration_ms > 0 AND NOT is_longform_mix
)
SELECT r.event_id AS play_id, r.is_skip, r.rn,
       r.started_at_utc, r.ended_at_utc,
       (r.started_at_utc AT TIME ZONE 'UTC') AT TIME ZONE r.tz AS started_at_local,
       r.tz, r.country, r.country_imputed, r.track_id, r.artist_id, r.album_id,
       r.session_id::BIGINT AS session_id, r.session_index::INTEGER AS session_index,
       r.new_session_10, r.new_session_30, r.ms_played,
       CASE WHEN r.ms_played IS NOT NULL THEN r.ms_played
            WHEN r.duration_ms > 0 THEN floor(r.duration_ms * med.m)::BIGINT
            ELSE 210000 END AS ms_imputed,
       CASE WHEN r.ms_played IS NULL OR r.duration_ms IS NULL OR r.duration_ms <= 0 OR r.is_longform_mix THEN NULL
            ELSE least(r.ms_played / r.duration_ms, 1.0) END AS completion_ratio,
       r.source, r.match_pass, r.match_gap_sec, r.platform_family, r.shuffle, r.offline, r.incognito,
       r.reason_start, r.reason_end, r.skipped
FROM w8_rows r CROSS JOIN med;

INSERT INTO plays SELECT * EXCLUDE (is_skip, rn) FROM w8_facts WHERE NOT is_skip;
INSERT INTO skips SELECT * EXCLUDE (is_skip, rn) FROM w8_facts WHERE is_skip;

-- 8. sessions
INSERT INTO sessions
WITH plat AS (
    SELECT session_id, platform_family,
           row_number() OVER (PARTITION BY session_id ORDER BY count(*) DESC, min(rn)) AS k
    FROM w8_facts WHERE platform_family IS NOT NULL GROUP BY session_id, platform_family
), agg AS (
    SELECT session_id, min(started_at_utc) AS started_at_utc, max(ended_at_utc) AS ended_at_utc,
           arg_min(started_at_local, rn) AS started_at_local, arg_min(tz, rn) AS tz,
           count(*) FILTER (WHERE NOT is_skip)::INTEGER AS n_plays,
           count(*) FILTER (WHERE is_skip)::INTEGER AS n_skips,
           sum(ms_imputed)::BIGINT AS listen_ms,
           CASE WHEN count(DISTINCT source) = 1 THEN any_value(source) ELSE 'mixed' END AS sources
    FROM w8_facts GROUP BY session_id
)
SELECT a.session_id, a.started_at_utc, a.ended_at_utc, a.started_at_local, a.tz, a.n_plays, a.n_skips,
       a.listen_ms, p.platform_family, a.sources
FROM agg a LEFT JOIN plat p ON p.session_id = a.session_id AND p.k = 1;
