# Architecture Decision Records (ADRs)

Project decisions live in `CLAUDE.md` and `docs/PROJECT.md` (decision log). This file records
harness-level choices only.

- **ADR-001 (2026-10-26):** Installed claude-harness-hub v2.0, merged into the existing `CLAUDE.md`.
  `.spec/` tracks harness slices; `STATE.md` remains the wave/packet tracker.
- **ADR-002 (2026-11-03):** `CLAUDE.md` cut to a 3-line shim. Working rules, layout, commands and deploy
  moved to `docs/RULES.md`, so each rule lives in one place. Rejected: keep the 60-line `CLAUDE.md`,
  because the engine caps it at 5 lines and the same rules were repeated in `SYSTEM_SPEC.md` and `PROJECT.md`.
