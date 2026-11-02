"""Step 06 (W9 / W9b): two-tier genre taxonomy. Loads data/genre_map.csv and builds track_genre.

    uv run python -m pipeline.genre unmapped [--top N]          # unmapped tags by plays, for curation
    uv run python -m pipeline.genre summary                     # level & umbrella vs sub-style breakdown
    uv run python -m pipeline.genre inspect <query> [--top N]   # inspect raw tags & resolved styles
    uv run python -m pipeline.genre sensitivity                 # compare 15% step, 25% step, and ramp+hinge
"""

from __future__ import annotations

import argparse

import duckdb

from pipeline import config

GENRE_MAP_CSV = config.REPO_ROOT / "data" / "genre_map.csv"
MIN_SHARE = 0.15
PARENTS: tuple[str, ...] = (
    "electronic",
    "pop",
    "rock",
    "hip hop",
    "r&b",
    "country",
    "soundtrack",
    "classical",
    "jazz",
    "world",
)

PROFILES: dict[str, dict[str, float | bool]] = {
    "legacy_step_15": {
        "rho_min": 0.15,
        "rho_max": 0.15,
        "floor_min": 0.15,
        "floor_max": 0.15,
        "self_tag_only": True,
        "two_stage": False,
    },
    "hard_step_25": {
        "rho_min": 0.25,
        "rho_max": 0.25,
        "floor_min": 0.25,
        "floor_max": 0.25,
        "self_tag_only": False,
        "two_stage": True,
    },
    "ramp_soft_hinge": {
        "rho_min": 0.10,
        "rho_max": 0.30,
        "floor_min": 0.10,
        "floor_max": 0.20,
        "self_tag_only": False,
        "two_stage": True,
    },
}

LOAD_SQL = f"""
DELETE FROM genre_map;
INSERT INTO genre_map
SELECT lower(trim(tag)), nullif(trim(style), ''), nullif(trim(parent_genre), ''),
       lower(trim(is_genre)) = 'true', lower(trim(is_umbrella)) = 'true'
FROM read_csv('{GENRE_MAP_CSV}', header = true, all_varchar = true);
INSERT INTO genre_map
SELECT DISTINCT t, NULL, NULL, false, false FROM (
    SELECT y::VARCHAR AS t FROM range(1900, 2100) r(y)
    UNION ALL SELECT (y // 10 * 10)::VARCHAR || 's' FROM range(1900, 2100, 10) r(y)
    UNION ALL SELECT lpad((y % 100)::VARCHAR, 2, '0') || 's' FROM range(1900, 2100, 10) r(y)
) WHERE t NOT IN (SELECT tag FROM genre_map);
"""


def build_sql(
    *,
    rho_min: float = 0.10,
    rho_max: float = 0.30,
    floor_min: float = 0.10,
    floor_max: float = 0.20,
    self_tag_only: bool = False,
    two_stage: bool = True,
) -> str:
    """Return the parameterised track_genre rebuild SQL.

    - When self_tag_only=False (Option A default), all is_umbrella=true tags under a parent P
      merge into the canonical parent-umbrella bucket (parent_genre = P, style = P).
    - Both alpha(rho_p) and g(x) use explicit SQL CASE branches so rho_min == rho_max and
      floor_min == floor_max evaluate hard steps without dividing by zero.
    - When two_stage=True, Stage A applies g(s_P) at the parent level to lock parent budgets B_P,
      and Stage B applies g(w / track_w) within each surviving parent and scales styles to B_P.
      When two_stage=False (legacy_step_15), pruning runs in a single track-level stage.
    """
    style_expr = "m.style" if self_tag_only else "CASE WHEN m.is_umbrella THEN m.parent_genre ELSE m.style END"

    head_ctes = f"""
DELETE FROM track_genre;
INSERT INTO track_genre
WITH lvl AS (
    -- (track_id, level, tag, count)
    SELECT t.track_id, 'track' AS level, l.tag, l.count::DOUBLE AS cnt
    FROM dim_track t JOIN enr_lastfm_tags l
      ON l.entity_type = 'track' AND l.entity_key = t.artist_norm || '::' || t.full_norm
    UNION ALL
    -- MB recordings reach a track through any ISRC they list (isrc and mbid lookups) or, for
    -- search lookups, through the track's key; each recording counts once per track.
    SELECT track_id, 'track', lower(trim(g.tag)), 100.0
    FROM (
        SELECT DISTINCT t.track_id, r.genres
        FROM dim_track t
        JOIN (SELECT genres, unnest(isrcs) AS isrc FROM enr_mb_recording WHERE http_status = 200) r
          ON r.isrc = t.isrc
        UNION
        SELECT t.track_id, r.genres
        FROM dim_track t JOIN enr_mb_recording r
          ON r.lookup_kind = 'search' AND r.lookup_key = t.artist_norm || '::' || t.full_norm AND r.score >= 90
    ) x, unnest(x.genres) g(tag)
    UNION ALL
    SELECT t.track_id, 'album', l.tag, l.count::DOUBLE
    FROM dim_track t JOIN dim_album a USING (album_id) JOIN dim_artist pa ON pa.artist_id = a.primary_artist_id
    JOIN enr_lastfm_tags l
      ON l.entity_type = 'album' AND l.entity_key = pa.artist_norm || '::' || a.album_norm
    UNION ALL
    SELECT t.track_id, 'artist', l.tag, l.count::DOUBLE
    FROM dim_track t JOIN dim_artist d ON d.artist_id = t.primary_artist_id JOIN enr_lastfm_tags l
      ON l.entity_type = 'artist' AND l.entity_key = d.artist_norm
    UNION ALL
    SELECT t.track_id, 'artist', lower(trim(g.tag)), 100.0
    FROM dim_track t JOIN dim_artist d ON d.artist_id = t.primary_artist_id
    JOIN enr_spotify_artist s ON s.spotify_artist_id = d.spotify_artist_id, unnest(s.genres) g(tag)
    UNION ALL
    SELECT t.track_id, 'artist', lower(trim(g.tag)), 100.0
    FROM dim_track t JOIN dim_artist d ON d.artist_id = t.primary_artist_id
    JOIN enr_mb_artist m ON m.artist_mbid = d.artist_mbid, unnest(m.genres) g(tag)
    UNION ALL
    -- LLM-synthesised artist genres (Option 2). Gives 100.0 base weight per artist level.
    SELECT t.track_id, 'artist', lower(trim(split_part(unnest(llm.genres), '::', 2))), unnest(llm.weights) * 100.0
    FROM dim_track t
    JOIN dim_artist d ON d.artist_id = t.primary_artist_id
    JOIN enr_artist_genre_llm llm ON llm.artist_norm = d.artist_norm
    UNION ALL
    -- Discogs physical release styles (Option 4). Gives 80.0 base weight per artist level.
    SELECT t.track_id, 'artist', lower(trim(unnest(disc.styles))), 80.0
    FROM dim_track t
    JOIN dim_artist d ON d.artist_id = t.primary_artist_id
    JOIN enr_discogs_artist disc ON disc.artist_norm = d.artist_norm
),
styled AS (
    SELECT l.track_id, l.level, m.parent_genre, {style_expr} AS style, sum(l.cnt) AS cnt
    FROM lvl l JOIN genre_map m ON m.tag = l.tag AND m.is_genre
    GROUP BY ALL
),
norm AS (
    SELECT *, cnt / sum(cnt) OVER (PARTITION BY track_id, level) AS share FROM styled
),
combined AS (
    SELECT track_id, parent_genre, style,
           sum(share * CASE level WHEN 'track' THEN 1.0 WHEN 'album' THEN 0.7 ELSE 0.5 END) AS w,
           min(CASE level WHEN 'track' THEN 1 WHEN 'album' THEN 2 ELSE 3 END) AS lv
    FROM norm GROUP BY ALL
),
parent_stats AS (
    SELECT *,
           sum(w) OVER (PARTITION BY track_id, parent_genre) AS parent_w,
           coalesce(sum(w) FILTER (WHERE style <> parent_genre) OVER (PARTITION BY track_id, parent_genre), 0.0) AS sub_w,
           coalesce(sum(w) FILTER (WHERE style = parent_genre) OVER (PARTITION BY track_id, parent_genre), 0.0) AS umb_w,
           min(lv) OVER (PARTITION BY track_id, parent_genre) AS parent_lv
    FROM combined
),
alpha_calc AS (
    SELECT *,
           CASE
               WHEN parent_w <= 0.0 OR sub_w <= 0.0 THEN 0.0
               WHEN (sub_w / parent_w) >= {rho_max} THEN 1.0
               WHEN (sub_w / parent_w) <  {rho_min} THEN 0.0
               ELSE ((sub_w / parent_w) - {rho_min}) / nullif({rho_max} - {rho_min}, 0.0)
           END AS alpha
    FROM parent_stats
),
disagg AS (
    SELECT track_id, parent_genre, style,
           CASE
               WHEN style <> parent_genre THEN w + alpha * umb_w * (w / sub_w)
               ELSE (1.0 - alpha) * w
           END AS w,
           CASE
               WHEN style <> parent_genre AND alpha > 0.0 THEN least(lv, parent_lv)
               ELSE lv
           END AS lv
    FROM alpha_calc
    WHERE (CASE WHEN style <> parent_genre THEN w + alpha * umb_w * (w / sub_w) ELSE (1.0 - alpha) * w END) > 1e-12
),
"""
    if not two_stage:
        tail_ctes = f"""kept AS (
    SELECT track_id, parent_genre, style,
           CASE
               WHEN (w / sum(w) OVER (PARTITION BY track_id)) >= {floor_max} THEN w
               WHEN (w / sum(w) OVER (PARTITION BY track_id)) <  {floor_min} THEN 0.0
               ELSE w * ((w / sum(w) OVER (PARTITION BY track_id)) - {floor_min}) / nullif({floor_max} - {floor_min}, 0.0)
           END AS w,
           lv
    FROM disagg
    QUALIFY (
        CASE
            WHEN (w / sum(w) OVER (PARTITION BY track_id)) >= {floor_max} THEN w
            WHEN (w / sum(w) OVER (PARTITION BY track_id)) <  {floor_min} THEN 0.0
            ELSE w * ((w / sum(w) OVER (PARTITION BY track_id)) - {floor_min}) / nullif({floor_max} - {floor_min}, 0.0)
        END
    ) > 0.0
),
lev AS (
    SELECT track_id, min(lv) AS lv FROM kept GROUP BY 1
)
SELECT k.track_id, k.parent_genre, k.style, k.w / sum(k.w) OVER (PARTITION BY k.track_id),
       CASE e.lv WHEN 1 THEN 'track' WHEN 2 THEN 'album' ELSE 'artist' END
FROM kept k JOIN lev e USING (track_id);
"""
    else:
        tail_ctes = f"""parent_totals AS (
    SELECT track_id, parent_genre, sum(w) AS parent_w
    FROM disagg
    GROUP BY 1, 2
),
parent_shares AS (
    SELECT track_id, parent_genre, parent_w,
           sum(parent_w) OVER (PARTITION BY track_id) AS track_w,
           parent_w / sum(parent_w) OVER (PARTITION BY track_id) AS s_p,
           row_number() OVER (PARTITION BY track_id ORDER BY parent_w DESC, parent_genre ASC) AS p_rn
    FROM parent_totals
),
parent_hinge AS (
    SELECT track_id, parent_genre, parent_w, track_w, s_p, p_rn,
           CASE
               WHEN s_p >= {floor_max} THEN s_p
               WHEN s_p <  {floor_min} THEN 0.0
               ELSE s_p * (s_p - {floor_min}) / nullif({floor_max} - {floor_min}, 0.0)
           END AS g_p
    FROM parent_shares
),
parent_surviving AS (
    SELECT track_id, parent_genre, track_w,
           CASE
               WHEN max(g_p) OVER (PARTITION BY track_id) > 0.0 THEN g_p
               WHEN p_rn = 1 THEN s_p
               ELSE 0.0
           END AS w_tilde_p
    FROM parent_hinge
),
parent_budgets AS (
    SELECT track_id, parent_genre, track_w,
           w_tilde_p / sum(w_tilde_p) OVER (PARTITION BY track_id) AS b_p
    FROM parent_surviving
    WHERE w_tilde_p > 0.0
),
style_shares AS (
    SELECT d.track_id, d.parent_genre, d.style, d.w, d.lv, pb.b_p, pb.track_w,
           d.w / pb.track_w AS x_s,
           row_number() OVER (PARTITION BY d.track_id, d.parent_genre ORDER BY d.w DESC, d.style ASC) AS s_rn
    FROM disagg d
    JOIN parent_budgets pb USING (track_id, parent_genre)
),
style_hinge AS (
    SELECT *,
           CASE
               WHEN x_s >= {floor_max} THEN x_s
               WHEN x_s <  {floor_min} THEN 0.0
               ELSE x_s * (x_s - {floor_min}) / nullif({floor_max} - {floor_min}, 0.0)
           END AS g_s
    FROM style_shares
),
style_surviving AS (
    SELECT track_id, parent_genre, style, lv, b_p,
           CASE
               WHEN max(g_s) OVER (PARTITION BY track_id, parent_genre) > 0.0 THEN g_s
               WHEN s_rn = 1 THEN x_s
               ELSE 0.0
           END AS w_tilde_s
    FROM style_hinge
),
kept AS (
    SELECT track_id, parent_genre, style, lv,
           b_p * (w_tilde_s / sum(w_tilde_s) OVER (PARTITION BY track_id, parent_genre)) AS w
    FROM style_surviving
    WHERE w_tilde_s > 0.0
),
lev AS (
    SELECT track_id, min(lv) AS lv FROM kept GROUP BY 1
)
SELECT k.track_id, k.parent_genre, k.style,
       k.w / sum(k.w) OVER (PARTITION BY k.track_id),
       CASE e.lv WHEN 1 THEN 'track' WHEN 2 THEN 'album' ELSE 'artist' END
FROM kept k JOIN lev e USING (track_id);
"""
    return head_ctes + tail_ctes


BUILD_SQL = build_sql()


def build(
    con: duckdb.DuckDBPyConnection,
    *,
    rho_min: float = 0.10,
    rho_max: float = 0.30,
    floor_min: float = 0.10,
    floor_max: float = 0.20,
    self_tag_only: bool = False,
    two_stage: bool = True,
) -> None:
    """Rebuild track_genre using the specified disaggregation and floor parameters."""
    con.execute(
        build_sql(
            rho_min=rho_min,
            rho_max=rho_max,
            floor_min=floor_min,
            floor_max=floor_max,
            self_tag_only=self_tag_only,
            two_stage=two_stage,
        )
    )


def run(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(LOAD_SQL)
    build(con)


def unmapped(con: duckdb.DuckDBPyConnection, top: int) -> list[tuple[int, str]]:
    """Unmapped tags ranked by plays behind them (track, album and artist level)."""
    return con.execute("""
        WITH tagged AS (
            SELECT t.track_id, l.tag FROM dim_track t JOIN enr_lastfm_tags l
              ON l.entity_type = 'track' AND l.entity_key = t.artist_norm || '::' || t.full_norm
            UNION ALL
            SELECT t.track_id, l.tag FROM dim_track t JOIN dim_artist d ON d.artist_id = t.primary_artist_id
              JOIN enr_lastfm_tags l ON l.entity_type = 'artist' AND l.entity_key = d.artist_norm
            UNION ALL
            SELECT t.track_id, l.tag FROM dim_track t JOIN dim_album a USING (album_id)
              JOIN dim_artist d ON d.artist_id = a.primary_artist_id
              JOIN enr_lastfm_tags l ON l.entity_type = 'album' AND l.entity_key = d.artist_norm || '::' || a.album_norm
            UNION ALL
            SELECT t.track_id, lower(trim(g.tag)) FROM dim_track t JOIN dim_artist d ON d.artist_id = t.primary_artist_id
              JOIN enr_spotify_artist s ON s.spotify_artist_id = d.spotify_artist_id, unnest(s.genres) g(tag)
            UNION ALL
            SELECT t.track_id, lower(trim(g.tag)) FROM dim_track t JOIN dim_artist d ON d.artist_id = t.primary_artist_id
              JOIN enr_mb_artist m ON m.artist_mbid = d.artist_mbid, unnest(m.genres) g(tag)
        ), pc AS (SELECT track_id, count(*) AS n FROM plays GROUP BY 1)
        SELECT sum(pc.n)::BIGINT AS p, tag FROM (SELECT DISTINCT track_id, tag FROM tagged) x
        JOIN pc USING (track_id) WHERE tag NOT IN (SELECT tag FROM genre_map)
        GROUP BY tag ORDER BY p DESC, tag LIMIT ?""", [top]).fetchall()


def summary(con: duckdb.DuckDBPyConnection) -> str:
    """Human-readable breakdown of track_genre coverage by level and umbrella vs specific sub-style."""
    lvl_rows = con.execute("""
        WITH pc AS (SELECT track_id, count(*) AS n FROM plays GROUP BY 1)
        SELECT g.level,
               count(DISTINCT g.track_id) AS tracks,
               round(sum(coalesce(pc.n, 0) * g.weight))::BIGINT AS weighted_plays
        FROM track_genre g LEFT JOIN pc USING (track_id)
        GROUP BY 1 ORDER BY 3 DESC
    """).fetchall()
    parent_rows = con.execute("""
        WITH pc AS (SELECT track_id, count(*) AS n FROM plays GROUP BY 1)
        SELECT g.parent_genre,
               round(sum(coalesce(pc.n, 0) * g.weight) FILTER (WHERE g.style <> g.parent_genre))::BIGINT AS substyle_plays,
               round(sum(coalesce(pc.n, 0) * g.weight) FILTER (WHERE g.style = g.parent_genre))::BIGINT AS umbrella_plays,
               round(100.0 * coalesce(sum(coalesce(pc.n, 0) * g.weight) FILTER (WHERE g.style <> g.parent_genre), 0)
                     / nullif(sum(coalesce(pc.n, 0) * g.weight), 0), 1) AS substyle_pct
        FROM track_genre g LEFT JOIN pc USING (track_id)
        GROUP BY 1 ORDER BY (coalesce(substyle_plays, 0) + coalesce(umbrella_plays, 0)) DESC
    """).fetchall()
    lines = ["=== Specificity Level (track vs album vs artist) ===", "level\ttracks\tweighted_plays"]
    for lv, tr, pl in lvl_rows:
        lines.append(f"{lv}\t{tr}\t{pl}")
    lines.append("\n=== Parent Genre: Specific Sub-Styles vs Umbrella Self-Tag ===")
    lines.append("parent_genre\tsubstyle_plays\tumbrella_plays\tsubstyle_pct")
    for pg, sub_p, umb_p, pct in parent_rows:
        lines.append(f"{pg}\t{sub_p or 0}\t{umb_p or 0}\t{pct or 0.0}%")
    return "\n".join(lines)


def inspect_tracks(con: duckdb.DuckDBPyConnection, query: str, top: int = 25) -> str:
    """Inspect resolved track_genre rows and raw tags for artists/tracks matching query."""
    pat = f"%{query.strip().lower()}%"
    resolved = con.execute("""
        WITH pc AS (SELECT track_id, count(*) AS n FROM plays GROUP BY 1)
        SELECT a.name AS artist, t.title, coalesce(pc.n, 0) AS plays,
               g.parent_genre, g.style, round(g.weight, 3) AS weight, g.level
        FROM dim_track t
        JOIN dim_artist a ON a.artist_id = t.primary_artist_id
        LEFT JOIN track_genre g USING (track_id)
        LEFT JOIN pc USING (track_id)
        WHERE a.artist_norm ILIKE ? OR t.full_norm ILIKE ? OR lower(a.name) ILIKE ? OR lower(t.title) ILIKE ?
        ORDER BY plays DESC, a.name, t.title, g.weight DESC
        LIMIT ?
    """, [pat, pat, pat, pat, top]).fetchall()
    lines = [f"=== Resolved track_genre for {query!r} (top {top}) ===",
             "artist\ttitle\tplays\tparent_genre\tstyle\tweight\tlevel"]
    for r in resolved:
        lines.append("\t".join(str(x) for x in r))
    return "\n".join(lines)


def _cliff_jump_for_profile(params: dict[str, float | bool]) -> float:
    """Evaluate max L1 output weight jump across a +/- 0.01 share perturbation around 0.15 and 0.25."""
    rho_min = float(params["rho_min"])
    rho_max = float(params["rho_max"])
    floor_min = float(params["floor_min"])
    floor_max = float(params["floor_max"])

    def eval_alpha(rho: float) -> float:
        if rho >= rho_max:
            return 1.0
        if rho < rho_min:
            return 0.0
        return (rho - rho_min) / (rho_max - rho_min) if rho_max > rho_min else 0.0

    def eval_g(x: float) -> float:
        if x >= floor_max:
            return x
        if x < floor_min:
            return 0.0
        return x * (x - floor_min) / (floor_max - floor_min) if floor_max > floor_min else 0.0

    max_jump = 0.0
    for theta in (0.15, 0.25):
        lo, hi = theta - 0.01, theta + 0.01
        # Within-parent umbrella -> specific transfer L1 jump (weight moves between umbrella and specific)
        a_lo, a_hi = eval_alpha(lo), eval_alpha(hi)
        umb_lo = (1.0 - a_lo) * (1.0 - lo)
        spec_lo = lo + a_lo * (1.0 - lo)
        umb_hi = (1.0 - a_hi) * (1.0 - hi)
        spec_hi = hi + a_hi * (1.0 - hi)
        jump_rho = abs(umb_hi - umb_lo) + abs(spec_hi - spec_lo)
        # Parent soft-floor renormalisation L1 jump for a 2-parent track (theta, 1 - theta)
        g1_lo, g2_lo = eval_g(lo), eval_g(1.0 - lo)
        b1_lo = g1_lo / (g1_lo + g2_lo)
        g1_hi, g2_hi = eval_g(hi), eval_g(1.0 - hi)
        b1_hi = g1_hi / (g1_hi + g2_hi)
        jump_floor = 2.0 * abs(b1_hi - b1_lo)
        max_jump = max(max_jump, jump_rho, jump_floor)
    return round(max_jump, 4)


def sensitivity(con: duckdb.DuckDBPyConnection) -> str:
    """Compare legacy_step_15, hard_step_25, and ramp_soft_hinge side by side."""
    con.execute(LOAD_SQL)
    lines = [
        "=== Genre Taxonomy Sensitivity Check ===",
        "profile\tspecific_style_share\tmax_cliff_jump\tmean_styles_per_track",
    ]
    for name, params in PROFILES.items():
        build(con, **params)  # type: ignore[arg-type]
        spec_share = con.execute("""
            SELECT coalesce(
                sum(weight) FILTER (WHERE style <> parent_genre)
                / nullif(sum(weight), 0.0),
                0.0
            )
            FROM track_genre
            WHERE parent_genre IN ('electronic', 'rock')
        """).fetchone()[0]
        mean_styles = con.execute("""
            SELECT coalesce(avg(cnt), 0.0)
            FROM (SELECT track_id, count(*) AS cnt FROM track_genre GROUP BY 1)
        """).fetchone()[0]
        cliff = _cliff_jump_for_profile(params)
        lines.append(f"{name}\t{spec_share:.4f}\t{cliff:.4f}\t{mean_styles:.3f}")
    # Restore default production rule
    build(con)
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(prog="pipeline.genre")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("unmapped", help="print unmapped tags by plays")
    u.add_argument("--top", type=int, default=50)
    sub.add_parser("summary", help="print level and sub-style disaggregation summary")
    ins = sub.add_parser("inspect", help="inspect resolved genres for an artist or track")
    ins.add_argument("query", help="artist or track substring")
    ins.add_argument("--top", type=int, default=25)
    sub.add_parser("sensitivity", help="compare 15% step, 25% step, and ramp+soft-hinge profiles")
    args = ap.parse_args()
    con = duckdb.connect(str(config.MUSIC_DB), read_only=args.cmd != "sensitivity")
    if args.cmd == "unmapped":
        for plays, tag in unmapped(con, args.top):
            print(f"{plays}\t{tag}")
    elif args.cmd == "summary":
        print(summary(con))
    elif args.cmd == "inspect":
        print(inspect_tracks(con, args.query, args.top))
    elif args.cmd == "sensitivity":
        print(sensitivity(con))


if __name__ == "__main__":
    main()
