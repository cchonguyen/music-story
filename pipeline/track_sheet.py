"""W15: track genre sheet. Export track genres for editing, import edits back as track overrides.

    uv run python -m pipeline.track_sheet export --out PATH [--min-plays 3]
    uv run python -m pipeline.track_sheet import PATH [--dry-run]

Precedence per track, applied by run() (pipeline step 06b, after genre.py has rebuilt track_genre):
  1. A track edit replaces everything else for that track.
  2. An artist edit (pipeline/artist_sheet.py) replaces the automatic genres of every track by that artist.
  3. Otherwise the automatic genre from step 06 stands.
Edits live in DATA_DIR/track_genre_overrides.csv and are copied into table track_genre_override.
A track whose sheet genres match its current genres is not stored as an edit. Reverting a track
to automatic genres is not supported yet.
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

from pipeline import artist_sheet, config

MIN_PLAYS = 3
DEFAULT_OVERRIDES: Path = (
    config.DATA_DIR / "track_genre_overrides.csv"
    if config.DATA_DIR is not None
    else config.REPO_ROOT / "build" / "track_genre_overrides.csv"
)
EXPORT_HEADER = ["track_id", "title", "artist", "plays", "parent_genre", "style", "share", "source"]
OVERRIDE_HEADER = ["track_id", "parent_genre", "style", "share"]
REQUIRED_COLUMNS = ("track_id", "parent_genre", "style", "share")
SAME_TOLERANCE = 0.0005

Genre = tuple[Any, Any, Any]
Row = dict[str, Any]


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


def rows(con: duckdb.DuckDBPyConnection, min_plays: int = MIN_PLAYS) -> list[Row]:
    """One dict per (track, genre) for tracks with at least min_plays plays. Tracks with no genre get one blank row."""
    sql = """
WITH tracks AS (
    SELECT t.track_id, t.title, a.name AS artist, count(p.play_id) AS plays
    FROM dim_track t
    JOIN dim_artist a ON a.artist_id = t.primary_artist_id
    LEFT JOIN plays p ON p.track_id = t.track_id
    GROUP BY 1, 2, 3
    HAVING count(p.play_id) >= ?
)
SELECT t.track_id, t.title, t.artist, t.plays, g.parent_genre, g.style,
       g.weight / nullif(sum(g.weight) OVER (PARTITION BY t.track_id), 0) AS share,
       g.level
FROM tracks t
LEFT JOIN track_genre g ON g.track_id = t.track_id
ORDER BY t.plays DESC, t.track_id, share DESC NULLS LAST
"""
    out: list[Row] = []
    for track_id, title, artist, plays, parent, style, share, level in con.execute(sql, [min_plays]).fetchall():
        out.append(
            {
                "track_id": track_id,
                "title": title,
                "artist": artist,
                "plays": int(plays),
                "parent_genre": parent,
                "style": style,
                "share": None if share is None else round(float(share), 4),
                "source": level or "none",
            }
        )
    return out


def to_csv(rows_in: list[Row]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(EXPORT_HEADER)
    for r in rows_in:
        share = r.get("share")
        writer.writerow(
            [
                r["track_id"],
                r["title"],
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


def validate(groups: dict[str, list[Row]], con: duckdb.DuckDBPyConnection) -> list[str]:
    known = {r[0] for r in con.execute("SELECT track_id FROM dim_track").fetchall()}
    genres = artist_sheet._valid_genres(con)
    errors: list[str] = []
    for key, group in groups.items():
        if key not in known:
            errors.append(f"unknown track_id: {key or '(blank)'}")
            continue
        if any(not _text(r.get("style")) for r in group):
            if len(group) > 1:
                errors.append(f"{key}: a blank style must be the only row for the track (clears genres)")
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


def _current_map(con: duckdb.DuckDBPyConnection) -> dict[str, list[Genre]]:
    out: dict[str, list[Genre]] = {}
    for track_id, parent, style, weight in con.execute(
        "SELECT track_id, parent_genre, style, weight FROM track_genre"
    ).fetchall():
        out.setdefault(track_id, []).append((parent, style, weight))
    for key, items in out.items():
        total = sum(w for _, _, w in items) or 1.0
        out[key] = [(p, s, round(w / total, 4)) for p, s, w in items]
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
            key = _text(r.get("track_id"))
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


def load_track_overrides(con: duckdb.DuckDBPyConnection, overrides_path: Path | None = None) -> int:
    """Copy the track edits CSV into table track_genre_override. Returns the row count."""
    path = DEFAULT_OVERRIDES if overrides_path is None else Path(overrides_path)
    overrides = _read_override_file(path)
    con.execute(
        "CREATE OR REPLACE TABLE track_genre_override (track_id VARCHAR, parent_genre VARCHAR, style VARCHAR, "
        "share DOUBLE)"
    )
    flat = [(key, p, s, sh) for key, items in overrides.items() for p, s, sh in items]
    if flat:
        con.executemany("INSERT INTO track_genre_override VALUES (?, ?, ?, ?)", flat)
    return len(flat)


def apply(con: duckdb.DuckDBPyConnection, overrides_path: Path | None = None) -> dict[str, int]:
    """Rewrite track_genre so track edits, then artist edits, replace the automatic genres. Safe to rerun."""
    artist_sheet.load_overrides(con)
    track_edits = load_track_overrides(con, overrides_path)
    con.execute("CREATE OR REPLACE TEMP TABLE w15_manual AS SELECT DISTINCT track_id FROM track_genre_override")
    con.execute(
        "CREATE OR REPLACE TEMP TABLE w15_artist AS "
        "SELECT t.track_id, o.artist_key FROM dim_track t "
        "JOIN (SELECT DISTINCT artist_key FROM artist_genre_override) o ON o.artist_key = t.artist_norm "
        "WHERE t.track_id NOT IN (SELECT track_id FROM w15_manual)"
    )
    con.execute(
        "DELETE FROM track_genre WHERE track_id IN (SELECT track_id FROM w15_manual) "
        "OR track_id IN (SELECT track_id FROM w15_artist)"
    )
    con.execute(
        "INSERT INTO track_genre SELECT track_id, parent_genre, style, share, 'manual' "
        "FROM track_genre_override WHERE style IS NOT NULL"
    )
    con.execute(
        "INSERT INTO track_genre SELECT w.track_id, o.parent_genre, o.style, o.share, 'artist' "
        "FROM w15_artist w JOIN artist_genre_override o ON o.artist_key = w.artist_key WHERE o.style IS NOT NULL"
    )
    artist_rows = con.execute(
        "SELECT count(*) FROM track_genre WHERE level = 'artist'"
    ).fetchone()[0]
    return {"track_edits": track_edits, "artist_carried_rows": int(artist_rows)}


def import_sheet(
    con: duckdb.DuckDBPyConnection,
    path: Path | str,
    dry_run: bool = False,
    overrides_path: Path | str | None = None,
) -> dict[str, Any]:
    target = DEFAULT_OVERRIDES if overrides_path is None else Path(overrides_path)
    report: dict[str, Any] = {"errors": [], "changed": [], "unchanged_count": 0}
    try:
        parsed = parse_csv(Path(path).read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        report["errors"] = [str(exc)]
        return report

    groups: dict[str, list[Row]] = {}
    for r in parsed:
        groups.setdefault(r["track_id"], []).append(r)
    report["errors"] = validate(groups, con)
    if report["errors"]:
        return report

    overrides = _read_override_file(target)
    current = _current_map(con)
    unchanged = 0
    for key, group in groups.items():
        new = normalise(group)
        if _same(new, current.get(key, [])):
            unchanged += 1
        else:
            overrides[key] = list(new) if new else [(None, None, None)]
            report["changed"].append(key)
    report["unchanged_count"] = unchanged

    if dry_run:
        return report
    _write_override_file(target, overrides)
    report["apply"] = apply(con, target)
    return report


def run(con: duckdb.DuckDBPyConnection) -> None:
    """Pipeline step 06b: apply track and artist edits on top of the automatic track genres."""
    apply(con)


def _cmd_export(args: argparse.Namespace) -> None:
    con = duckdb.connect(str(config.MUSIC_DB), read_only=True)
    try:
        data = rows(con, args.min_plays)
    finally:
        con.close()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_csv(data), encoding="utf-8")
    print(f"{len({r['track_id'] for r in data})} tracks, {len(data)} rows -> {out}")


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
    summary = f"changed {len(report['changed'])}, unchanged {report['unchanged_count']}"
    if args.dry_run:
        summary += " (dry run, nothing written)"
    print(summary)
    return 0


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="pipeline.track_sheet")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="write the track genre sheet as CSV")
    ex.add_argument("--out", required=True, help="output CSV path")
    ex.add_argument("--min-plays", type=int, default=MIN_PLAYS)
    im = sub.add_parser("import", help="validate a sheet, store its edits and apply them")
    im.add_argument("path", help="edited CSV path")
    im.add_argument("--dry-run", action="store_true", help="validate and report without writing")
    args = ap.parse_args(argv)
    if args.cmd == "export":
        _cmd_export(args)
    else:
        sys.exit(_cmd_import(args))


if __name__ == "__main__":
    main()
