"""W14 / S1: artist genre sheet. Export artist genres for editing, import shares back as overrides.

    uv run python -m pipeline.artist_sheet export --out PATH [--min-plays 3]
    uv run python -m pipeline.artist_sheet import PATH [--dry-run]

Derived genres mirror the artist-level inputs of pipeline/genre.py. Overrides live in a CSV outside the
repo (DATA_DIR) and are copied into table artist_genre_override by load_overrides().
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import os
import sys
from pathlib import Path
from typing import Any

import duckdb

from pipeline import config

MIN_PLAYS = 3
DEFAULT_OVERRIDES: Path = (
    config.DATA_DIR / "artist_genre_overrides.csv"
    if config.DATA_DIR is not None
    else config.REPO_ROOT / "build" / "artist_genre_overrides.csv"
)
EXPORT_HEADER = ["artist_key", "artist", "plays", "parent_genre", "style", "share", "source"]
OVERRIDE_HEADER = ["artist_key", "parent_genre", "style", "share"]
REQUIRED_COLUMNS = ("artist_key", "parent_genre", "style", "share")
SAME_TOLERANCE = 0.0005

# Override entry: (parent_genre, style, share). A cleared artist is stored as [(None, None, None)].
Genre = tuple[Any, Any, Any]
Row = dict[str, Any]

# Stand-in for the artist-tag union when no source table exists. Yields no rows.
EMPTY_BASE = "SELECT NULL::VARCHAR AS artist_norm, NULL::VARCHAR AS tag, NULL::DOUBLE AS w WHERE false"


def _has_table(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    count = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_catalog = current_database() "
        "AND table_schema = current_schema() AND table_name = ?",
        [name],
    ).fetchone()[0]
    return bool(count)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _share_of(row: Row) -> float | None:
    raw = row.get("share")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _fmt_share(value: float) -> str:
    return f"{round(float(value), 4):.4f}".rstrip("0").rstrip(".") or "0"


def _sorted(rows: list[Row]) -> list[Row]:
    return sorted(rows, key=lambda r: (-r["plays"], r["artist_key"], -(r["share"] or 0.0)))


def _source_parts(con: duckdb.DuckDBPyConnection) -> list[str]:
    """One SELECT per artist-level tag source, each yielding (artist_norm, tag, w)."""
    parts: list[str] = []
    if _has_table(con, "enr_lastfm_tags"):
        parts.append(
            "SELECT d.artist_norm AS artist_norm, lower(trim(l.tag)) AS tag, l.count::DOUBLE AS w "
            "FROM dim_artist d JOIN enr_lastfm_tags l ON l.entity_type = 'artist' AND l.entity_key = d.artist_norm"
        )
    if _has_table(con, "enr_spotify_artist"):
        parts.append(
            "SELECT d.artist_norm AS artist_norm, lower(trim(g.tag)) AS tag, 100.0::DOUBLE AS w "
            "FROM dim_artist d JOIN enr_spotify_artist s ON s.spotify_artist_id = d.spotify_artist_id, "
            "unnest(s.genres) g(tag)"
        )
    if _has_table(con, "enr_mb_artist"):
        parts.append(
            "SELECT d.artist_norm AS artist_norm, lower(trim(g.tag)) AS tag, 100.0::DOUBLE AS w "
            "FROM dim_artist d JOIN enr_mb_artist m ON m.artist_mbid = d.artist_mbid, unnest(m.genres) g(tag)"
        )
    if _has_table(con, "enr_artist_genre_llm"):
        # genres hold 'parent::style'; the style part is treated as a tag, as in pipeline/genre.py.
        parts.append(
            "SELECT d.artist_norm AS artist_norm, lower(trim(split_part(unnest(llm.genres), '::', 2))) AS tag, "
            "unnest(llm.weights) * 100.0 AS w "
            "FROM dim_artist d JOIN enr_artist_genre_llm llm ON llm.artist_norm = d.artist_norm"
        )
    if _has_table(con, "enr_discogs_artist"):
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
    if not _has_table(con, "artist_genre_override"):
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
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(EXPORT_HEADER)
    for r in rows_in:
        share = r.get("share")
        writer.writerow(
            [
                r["artist_key"],
                r["artist"],
                int(r["plays"]),
                _text(r.get("parent_genre")),
                _text(r.get("style")),
                "" if share is None else _fmt_share(share),
                r["source"],
            ]
        )
    return buf.getvalue()


def parse_csv(text: str) -> list[Row]:
    reader = csv.DictReader(io.StringIO(text))
    fields = reader.fieldnames or []
    missing = [c for c in REQUIRED_COLUMNS if c not in fields]
    if missing:
        raise ValueError(f"missing column(s): {', '.join(missing)}")
    return [{k: _text(v) for k, v in r.items() if k} for r in reader]


def _valid_genres(con: duckdb.DuckDBPyConnection) -> set[tuple[str, str]]:
    """(parent, style) pairs an artist may use. Umbrella tags collapse to (parent, parent)."""
    pairs: set[tuple[str, str]] = set()
    sql = "SELECT style, parent_genre, is_umbrella FROM genre_map WHERE is_genre"
    for style, parent, umbrella in con.execute(sql).fetchall():
        if style and parent:
            pairs.add((parent, style))
            if umbrella:
                pairs.add((parent, parent))
    return pairs


def validate(groups: dict[str, list[Row]], con: duckdb.DuckDBPyConnection) -> list[str]:
    known = {r[0] for r in con.execute("SELECT artist_norm FROM dim_artist").fetchall()}
    genres = _valid_genres(con)
    errors: list[str] = []
    for key, group in groups.items():
        if key not in known:
            errors.append(f"unknown artist_key: {key or '(blank)'}")
            continue
        if any(not _text(r.get("style")) for r in group):
            if len(group) > 1:
                errors.append(f"{key}: a blank style must be the only row for the artist (clears genres)")
            continue
        seen: set[str] = set()
        total = 0.0
        share_error = False
        for r in group:
            parent, style = _text(r.get("parent_genre")), _text(r.get("style"))
            share = _share_of(r)
            if (parent, style) not in genres:
                errors.append(f"{key}: '{style}' is not a genre under '{parent}'")
            if style in seen:
                errors.append(f"{key}: duplicate style '{style}'")
            seen.add(style)
            if share is None or share <= 0:
                errors.append(f"{key}: share for '{style}' must be a positive number")
                share_error = True
            else:
                total += share
        if not share_error and total <= 0:
            errors.append(f"{key}: total share must be above 0")
    return errors


def normalise(group: list[Row]) -> list[Genre]:
    """(parent, style, share) with shares divided by their total and rounded to 4 dp. Empty when cleared."""
    items: list[tuple[str, str, float]] = []
    for r in group:
        style = _text(r.get("style"))
        share = _share_of(r)
        if style and share is not None and share > 0:
            items.append((_text(r.get("parent_genre")), style, share))
    total = sum(sh for _, _, sh in items)
    if total <= 0:
        return []
    return [(p, s, round(sh / total, 4)) for p, s, sh in items]


def _derived_map(con: duckdb.DuckDBPyConnection) -> dict[str, list[Genre]]:
    out: dict[str, list[Genre]] = {}
    for r in _derived_rows(con, 0):
        if r["style"] is not None:
            out.setdefault(r["artist_key"], []).append((r["parent_genre"], r["style"], r["share"]))
    return out


def _same(new: list[Genre], old: list[Genre]) -> bool:
    if {(p, s) for p, s, _ in new} != {(p, s) for p, s, _ in old}:
        return False
    old_share = {(p, s): sh for p, s, sh in old}
    return all(abs(sh - old_share[(p, s)]) <= SAME_TOLERANCE + 1e-9 for p, s, sh in new)


def _read_override_file(path: Path) -> dict[str, list[Genre]]:
    if not path.exists():
        return {}
    out: dict[str, list[Genre]] = {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            key = _text(r.get("artist_key"))
            style = _text(r.get("style"))
            if not key:
                continue
            if not style:
                out[key] = [(None, None, None)]
            else:
                out.setdefault(key, []).append((_text(r.get("parent_genre")) or None, style, float(r["share"])))
    return out


def _write_override_file(path: Path, overrides: dict[str, list[Genre]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(OVERRIDE_HEADER)
        for key in sorted(overrides):
            for parent, style, share in overrides[key]:
                if style is None:
                    writer.writerow([key, "", "", ""])
                else:
                    writer.writerow([key, parent or "", style, _fmt_share(share)])
    os.replace(tmp, path)


def load_overrides(con: duckdb.DuckDBPyConnection, overrides_path: Path | None = None) -> int:
    """Copy the overrides CSV into table artist_genre_override. Returns the row count."""
    path = DEFAULT_OVERRIDES if overrides_path is None else Path(overrides_path)
    overrides = _read_override_file(path)
    con.execute(
        "CREATE OR REPLACE TABLE artist_genre_override (artist_key VARCHAR, parent_genre VARCHAR, style VARCHAR, "
        "share DOUBLE)"
    )
    flat = [(key, p, s, sh) for key, items in overrides.items() for p, s, sh in items]
    if flat:
        con.executemany("INSERT INTO artist_genre_override VALUES (?, ?, ?, ?)", flat)
    return len(flat)


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

    overrides = _read_override_file(target)
    derived = _derived_map(con)
    unchanged = 0
    for key, group in groups.items():
        new = normalise(group)
        if _same(new, derived.get(key, [])):
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
    _write_override_file(target, overrides)
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
