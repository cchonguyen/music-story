# Antigravity & External Agent Contract (music-story)

## 1. Pre-Flight Inspection
Before modifying files or generating plans:
- Read `CLAUDE.md` (project commands and conventions).
- Read `STATE.md` (current wave, packet status, decisions).
- Read `.spec/SESSION_HANDOFF.md` (where Claude or the last session left off).
- The full external co-development contract is `.spec/EXTERNAL_AGENT_RULES.md`.

## 2. Bounded Execution & Git Rigor
- **Strict Branch & PR Paradigm:** NEVER commit or push directly to `main`. Every change must live on an isolated feature branch (e.g. `antigravity/<feature>` or `feat/<feature>`) and be merged via a GitHub Pull Request.
- **Spoke Repository Protection:** NEVER modify or delete files inside `.claude/`, `.harness/`, or `.harness-version`.
- **Pre-Commit Verification:** Run project checks before opening a PR:
  - `uv run pytest -q`
  - `uv run ruff check`
- **Mandatory Baton Pass:** When concluding an implementation session, record your verification status and next steps in `.spec/SESSION_HANDOFF.md`.
