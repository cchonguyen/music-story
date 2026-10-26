# System Specification & Contracts

## 1. Core Scope & MVP Boundaries
- Pipeline and site as defined in `docs/PROJECT.md`; table contract is `sql/schema.sql`.

## 2. Strictly Out of Scope ("Do NOT Build" List)
- No raw exports or databases in the repo or any prompt (including `/prep-audit` packets).
- No schema changes without the lead updating `tests/test_schema.py` and `STATE.md`.
- No public URLs: `workers_dev` and `preview_urls` stay off.

## 3. Data Models & Module Boundaries
- `sql/` schema + SQL steps, `pipeline/` Python steps (normalisation only in `normalize.py`),
  `site/` Observable Framework site, `specs/` work-packet specs.
