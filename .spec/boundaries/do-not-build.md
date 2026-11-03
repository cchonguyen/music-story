# Do NOT Build (Sector 220)

Moved from `.spec/SYSTEM_SPEC.md` section 2 on 2026-11-03.

- No raw exports or databases in the repo or any prompt (including `/prep-audit` packets).
- No schema changes without the lead updating `tests/test_schema.py` and `STATE.md`.
- No public URLs: `workers_dev` and `preview_urls` stay off.
- No server code: the Worker is assets-only, so there is no runtime, database client or secret at the edge.
