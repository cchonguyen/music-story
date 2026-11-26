"""W14 / S1: artist genre sheet. Export artist genres for editing, import shares back as overrides.

    uv run python -m pipeline.artist_sheet export --out PATH [--min-plays 3]
    uv run python -m pipeline.artist_sheet import PATH [--dry-run]

Derived genres mirror the artist-level inputs of pipeline/genre.py. Overrides live in a CSV outside the
repo (DATA_DIR) and are copied into table artist_genre_override by load_overrides().
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import duckdb

from pipeline import config
from pipeline import genre_sheet_common as common
from pipeline.genre_sheet_common import Genre, Row, normalise

MIN_PLAYS = 3
DEFAULT_OVERRIDES: Path = (
    config.DATA_DIR / "artist_genre_overrides.csv"
    if config.DATA_DIR is not None
    else config.REPO_ROOT / "build" / "artist_genre_overrides.csv"
)
EXPORT_HEADER = ["artist_key", "artist", "plays", "parent_genre", "style", "share", "source"]
OVERRIDE_HEADER = ["artist_key", "parent_genre", "style", "share"]
REQUIRED_COLUMNS = ("artist_key", "parent_genre", "style", "share")

# Stand-in for the artist-tag union when no source table exists. Yields no rows.
EMPTY_BASE = "SELECT NULL::VARCHAR AS artist_norm, NULL::VARCHAR AS tag, NULL::DOUBLE AS w WHERE false"


def _sorted(rows_in: list[Row]) -> list[Row]:
    return sorted(rows_in, key=lambda r: (-r["plays"], r["artist_key"], -(r["share"] or 0.0)))


def _source_parts(con: duckdb.DuckDBPyConnection) -> list[str]:
    """One SELECT per artist-level tag source, each yielding (artist_norm, tag, w)."""
    parts: list[str] = []
    if common.has_table(con, "enr_lastfm_tags"):
        parts.append(
            "SELECT d.artist_norm AS artist_norm, lower(trim(l.tag)) AS tag, l.count::DOUBLE AS w "
            "FROM dim_artist d JOIN enr_lastfm_tags l ON l.entity_type = 'artist' AND l.entity_key = d.artist_norm"
        )
    if common.has_table(con, "enr_spotify_artist"):
        parts.append(
            "SELECT d.artist_norm AS artist_norm, lower(trim(g.tag)) AS tag, 100.0::DOUBLE AS w "
            "FROM dim_artist d JOIN enr_spotify_artist s ON s.spotify_artist_id = d.spotify_artist_id, "
            "unnest(s.genres) g(tag)"
        )
    if common.has_table(con, "enr_mb_artist"):
        parts.append(
            "SELECT d.artist_norm AS artist_norm, lower(trim(g.tag)) AS tag, 100.0::DOUBLE AS w "
            "FROM dim_artist d JOIN enr_mb_artist m ON m.artist_mbid = d.artist_mbid, unnest(m.genres) g(tag)"
        )
    if common.has_table(con, "enr_artist_genre_llm"):
        # genres hold 'parent::style'; the style part is treated as a tag, as in pipeline/genre.py.
        parts.append(
            "SELECT d.artist_norm AS artist_norm, lower(trim(split_part(unnest(llm.genres), '::', 2))) AS tag, "
            "unnest(llm.weights) * 100.0 AS w "
            "FROM dim_artist d JOIN enr_artist_genre_llm llm ON llm.artist_norm = d.artist_norm"
        )
    if common.has_table(con, "enr_discogs_artist"):
        parts.append(
            "SELECT d.artist_norm AS artist_norm, lower(trim(unnest(disc.styles))) AS tag, 80.0::DOUBLE AS w "
            "FROM dim_artist d JOIN enr_discogs_artist disc ON disc.artist_norm = d.artist_norm"
        )
    return parts


def _derived_rows(con: duckdb.DuckDBPyConnection, min_plays: int) -> list[Row]:
    """Genres from the source tables only, ignoring overrides. Artists with no genres get one blank row."""
    base = " UNION ALL ".join(_source_parts(con)) or EMPTY_BASE
    sql = f"""
WITH base AS ({base}),
mapped AS (
    SELECT b.artist_norm, m.parent_genre,
           CASE WHEN m.is_umbrella THEN m.parent_genre ELSE m.style END AS style,
           sum(b.w) AS w
    FROM base b JOIN genre_map m ON m.tag = b.tag AND m.is_genre
    WHERE b.w > 0
    GROUP BY 1, 2, 3
),
artists AS (
    SELECT d.artist_norm, d.name, count(p.play_id) AS plays
    FROM dim_artist d LEFT JOIN plays p ON p.artist_id = d.artist_id
    GROUP BY 1, 2
    HAVING count(p.play_id) >= ?
)
SELECT a.artist_norm, a.name, a.plays, m.parent_genre, m.style,
       m.w / nullif(sum(m.w) OVER (PARTITION BY a.artist_norm), 0) AS share
FROM artists a LEFT JOIN mapped m ON m.artist_norm = a.artist_norm
"""
    out: list[Row] = []
    for key, name, plays, parent, style, share in con.execute(sql, [min_plays]).fetchall():
        out.append(
            {
                "artist_key": key,
                "artist": name,
                "plays": int(plays),
                "parent_genre": parent,
                "style": style,
                "share": None if share is None else round(float(share), 4),
                "source": "derived",
            }
        )
    return _sorted(out)


def _table_overrides(con: duckdb.DuckDBPyConnection) -> dict[str, list[Genre]]:
    if not common.has_table(con, "artist_genre_override"):
        return {}
    out: dict[str, list[Genre]] = {}
    sql = "SELECT artist_key, parent_genre, style, share FROM artist_genre_override ORDER BY artist_key, share DESC"
    for key, parent, style, share in con.execute(sql).fetchall():
        if style is None:
            out[key] = [(None, None, None)]
        else:
            out.setdefault(key, []).append((parent, style, share))
    return out


def _row(meta: Row, parent: Any, style: Any, share: Any, source: str) -> Row:
    return {
        "artist_key": meta["artist_key"],
        "artist": meta["artist"],
        "plays": int(meta["plays"]),
        "parent_genre": parent,
        "style": style,
        "share": share,
        "source": source,
    }


def _apply_overrides(derived: list[Row], overrides: dict[str, list[Genre]]) -> list[Row]:
    groups: dict[str, list[Row]] = {}
    for row in derived:
        groups.setdefault(row["artist_key"], []).append(row)
    out: list[Row] = []
    for key, group in groups.items():
        if key in overrides:
            out.extend(_row(group[0], p, s, sh, "manual") for p, s, sh in overrides[key])
        else:
            out.extend(group)
    return _sorted(out)


def rows(con: duckdb.DuckDBPyConnection, min_plays: int = MIN_PLAYS) -> list[Row]:
    """One dict per (artist, genre) with overrides applied. Artists below min_plays are left out."""
    return _apply_overrides(_derived_rows(con, min_plays), _table_overrides(con))


def to_csv(rows_in: list[Row]) -> str:
    return common.to_csv(rows_in, EXPORT_HEADER)


def parse_csv(text: str) -> list[Row]:
    return common.parse_csv(text, REQUIRED_COLUMNS)


def validate(groups: dict[str, list[Row]], con: duckdb.DuckDBPyConnection) -> list[str]:
    known = {r[0] for r in con.execute("SELECT artist_norm FROM dim_artist").fetchall()}
    return common.validate_groups(groups, known, common.valid_genres(con), "artist_key", "artist")


def _derived_map(con: duckdb.DuckDBPyConnection) -> dict[str, list[Genre]]:
    out: dict[str, list[Genre]] = {}
    for r in _derived_rows(con, 0):
        if r["style"] is not None:
            out.setdefault(r["artist_key"], []).append((r["parent_genre"], r["style"], r["share"]))
    return out


def load_overrides(con: duckdb.DuckDBPyConnection, overrides_path: Path | None = None) -> int:
    """Copy the overrides CSV into table artist_genre_override. Returns the row count."""
    return common.load_override_table(con, "artist_genre_override", "artist_key", overrides_path, DEFAULT_OVERRIDES)


def import_sheet(
    con: duckdb.DuckDBPyConnection,
    path: Path | str,
    dry_run: bool = False,
    overrides_path: Path | str | None = None,
) -> dict[str, Any]:
    target = DEFAULT_OVERRIDES if overrides_path is None else Path(overrides_path)
    report: dict[str, Any] = {"errors": [], "changed": [], "reverted": [], "unchanged_count": 0}
    try:
        parsed = parse_csv(Path(path).read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        report["errors"] = [str(exc)]
        return report

    groups: dict[str, list[Row]] = {}
    for r in parsed:
        groups.setdefault(r["artist_key"], []).append(r)
    report["errors"] = validate(groups, con)
    if report["errors"]:
        return report

    overrides = common.read_override_file(target, "artist_key")
    derived = _derived_map(con)
    unchanged = 0
    for key, group in groups.items():
        new = normalise(group)
        if common.same(new, derived.get(key, [])):
            if overrides.pop(key, None) is not None:
                report["reverted"].append(key)
            else:
                unchanged += 1
        else:
            overrides[key] = list(new) if new else [(None, None, None)]
            report["changed"].append(key)
    report["unchanged_count"] = unchanged

    if dry_run:
        return report
    common.write_override_file(target, overrides, OVERRIDE_HEADER)
    load_overrides(con, target)
    return report


def run(con: duckdb.DuckDBPyConnection) -> None:
    load_overrides(con)


def _cmd_export(args: argparse.Namespace) -> None:
    con = duckdb.connect(str(config.MUSIC_DB), read_only=True)
    try:
        data = rows(con, args.min_plays)
    finally:
        con.close()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_csv(data), encoding="utf-8")
    print(f"{len({r['artist_key'] for r in data})} artists, {len(data)} rows -> {out}")


def _cmd_import(args: argparse.Namespace) -> int:
    db = Path(config.MUSIC_DB)
    if not db.exists():
        print(f"database not found: {db}")
        return 1
    con = duckdb.connect(str(db))
    try:
        report = import_sheet(con, args.path, dry_run=args.dry_run)
    finally:
        con.close()
    for err in report["errors"]:
        print(err)
    if report["errors"]:
        print(f"{len(report['errors'])} error(s), nothing written")
        return 1
    summary = (
        f"changed {len(report['changed'])}, reverted {len(report['reverted'])}, "
        f"unchanged {report['unchanged_count']}"
    )
    if args.dry_run:
        summary += " (dry run, nothing written)"
    print(summary)
    return 0


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="pipeline.artist_sheet")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="write the artist genre sheet as CSV")
    ex.add_argument("--out", required=True, help="output CSV path")
    ex.add_argument("--min-plays", type=int, default=MIN_PLAYS)
    im = sub.add_parser("import", help="validate a sheet and store its overrides")
    im.add_argument("path", help="edited CSV path")
    im.add_argument("--dry-run", action="store_true", help="validate and report without writing")
    args = ap.parse_args(argv)
    if args.cmd == "export":
        _cmd_export(args)
    else:
        sys.exit(_cmd_import(args))


if __name__ == "__main__":
    main()
