# SESSION HANDOFF (updated 2026-11-26, end of W14 S2 session)
- **Active Branch / State:** `claude/artist-sheet-browser-csv` (from `origin/main`, S2 only). W14 is merged on main via PR #44 (merged by Charlie 10:23 UTC with pr-check and slice gate still red).
- **Done this session:** W14 spec, `pipeline/artist_sheet.py` export/import (S1, Slice 14), S2 browser button: `pipeline.site_data artist_genre_sheet` loader, `site/src/data/artist_genre_sheet.json.sh`, and "Artist genre sheet" section on `site/src/artists.md`.
- **Local checks (this session, S2):** `uv run pytest -q` all passed (incl. new loader test); `uv run ruff check` all checks passed; `npm run lint` exit 0; `cd site && npm run build` exit 0.
- **GitHub checks: NOT verified.** pr-check and the slice gate are blocked by a GitHub Actions billing/spending limit (Charlie to raise the Actions limit above $0). S2 has no CI run yet.
- **Harness hub:** PR #246 merged (issue-status runs only for `slice` issues). Charlie synced Concert-Tracker. Check that `harness-issue-status.yml` minutes stop climbing.
- **Open items:** overrides do not yet change `track_genre` (Genres, Songs, Explorer keep derived values); needs its own spec. Unverified commits on `claude/project-thread-n1gepr` (Charlie's Mac history) left alone by decision pending Charlie. Five one-line privacy-scrub changes on that branch from the audit thread must be kept.
- **Next step:** open a PR for `claude/artist-sheet-browser-csv` once Charlie approves the diff; re-run pr-check after billing is fixed.
