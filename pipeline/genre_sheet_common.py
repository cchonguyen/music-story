"""Shared CSV parsing, validation, normalisation, and override-table helpers for artist and track genre sheets."""

from __future__ import annotations

import csv
import io
import math
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import duckdb

SAME_TOLERANCE = 0.0005

Genre = tuple[Any, Any, Any]
Row = dict[str, Any]


def has_table(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    count = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_catalog = current_database() "
        "AND table_schema = current_schema() AND table_name = ?",
        [name],
    ).fetchone()[0]
    return bool(count)


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def share_of(row: Row) -> float | None:
    raw = row.get("share")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def fmt_share(value: float) -> str:
    return f"{round(float(value), 4):.4f}".rstrip("0").rstrip(".") or "0"


def to_csv(rows_in: list[Row], header: Sequence[str]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    for r in rows_in:
        share = r.get("share")
        out_row = []
        for col in header:
            if col == "plays":
                out_row.append(int(r["plays"]))
            elif col == "share":
                out_row.append("" if share is None else fmt_share(share))
            elif col in ("parent_genre", "style"):
                out_row.append(text(r.get(col)))
            else:
                out_row.append(r[col])
        writer.writerow(out_row)
    return buf.getvalue()


def parse_csv(text_in: str, required_columns: Sequence[str]) -> list[Row]:
    reader = csv.DictReader(io.StringIO(text_in))
    fields = reader.fieldnames or []
    missing = [c for c in required_columns if c not in fields]
    if missing:
        raise ValueError(f"missing column(s): {', '.join(missing)}")
    return [{k: text(v) for k, v in r.items() if k} for r in reader]


def valid_genres(con: duckdb.DuckDBPyConnection) -> set[tuple[str, str]]:
    """(parent, style) pairs an artist or track may use. Umbrella tags collapse to (parent, parent)."""
    pairs: set[tuple[str, str]] = set()
    sql = "SELECT style, parent_genre, is_umbrella FROM genre_map WHERE is_genre"
    for style, parent, umbrella in con.execute(sql).fetchall():
        if style and parent:
            pairs.add((parent, style))
            if umbrella:
                pairs.add((parent, parent))
    return pairs


def validate_groups(
    groups: dict[str, list[Row]],
    known: set[str],
    genres: set[tuple[str, str]],
    key_label: str,
    entity_label: str,
) -> list[str]:
    errors: list[str] = []
    for key, group in groups.items():
        if key not in known:
            errors.append(f"unknown {key_label}: {key or '(blank)'}")
            continue
        if any(not text(r.get("style")) for r in group):
            if len(group) > 1:
                errors.append(f"{key}: a blank style must be the only row for the {entity_label} (clears genres)")
            continue
        seen: set[tuple[str, str]] = set()
        total = 0.0
        share_error = False
        for r in group:
            parent, style = text(r.get("parent_genre")), text(r.get("style"))
            share = share_of(r)
            if share == 0:
                continue
            if (parent, style) not in genres:
                errors.append(f"{key}: '{style}' is not a genre under '{parent}'")
            if (parent, style) in seen:
                errors.append(f"{key}: duplicate style '{style}'")
            seen.add((parent, style))
            if share is None or share < 0:
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
        style = text(r.get("style"))
        share = share_of(r)
        if style and share is not None and share > 0:
            items.append((text(r.get("parent_genre")), style, share))
    total = sum(sh for _, _, sh in items)
    if total <= 0:
        return []
    return [(p, s, round(sh / total, 4)) for p, s, sh in items]


def same(new: list[Genre], old: list[Genre]) -> bool:
    if {(p, s) for p, s, _ in new} != {(p, s) for p, s, _ in old}:
        return False
    old_share = {(p, s): sh for p, s, sh in old}
    return all(abs(sh - old_share[(p, s)]) <= SAME_TOLERANCE + 1e-9 for p, s, sh in new)


def read_override_file(path: Path, key_col: str) -> dict[str, list[Genre]]:
    if not path.exists():
        return {}
    out: dict[str, list[Genre]] = {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            key = text(r.get(key_col))
            style = text(r.get("style"))
            if not key:
                continue
            if not style:
                out[key] = [(None, None, None)]
            else:
                out.setdefault(key, []).append((text(r.get("parent_genre")) or None, style, float(r["share"])))
    return out


def write_override_file(path: Path, overrides: dict[str, list[Genre]], header: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        for key in sorted(overrides):
            for parent, style, share in overrides[key]:
                if style is None:
                    writer.writerow([key, "", "", ""])
                else:
                    writer.writerow([key, parent or "", style, fmt_share(share)])
    os.replace(tmp, path)


def load_override_table(
    con: duckdb.DuckDBPyConnection,
    table: str,
    key_col: str,
    overrides_path: Path | None,
    default_overrides: Path,
) -> int:
    path = default_overrides if overrides_path is None else Path(overrides_path)
    overrides = read_override_file(path, key_col)
    con.execute(
        f"CREATE OR REPLACE TABLE {table} ({key_col} VARCHAR, parent_genre VARCHAR, style VARCHAR, share DOUBLE)"
    )
    flat = [(key, p, s, sh) for key, items in overrides.items() for p, s, sh in items]
    if flat:
        con.executemany(f"INSERT INTO {table} VALUES (?, ?, ?, ?)", flat)
    return len(flat)
