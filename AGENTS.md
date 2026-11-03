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

<!-- >>> harness >>> -->
## Harness rules for external agents (managed by the harness; edit in claude-harness-hub)

Before you change this repo, read `.spec/EXTERNAL_AGENT_RULES.md`. It is the full contract.

Rules that always apply:
1. Read `.spec/SESSION_HANDOFF.md` and check `Branch Owner`. Push only to a branch you own. If the owner is someone else, open `antigravity/<slice>` or post a PR review comment instead.
2. Record code review findings in `.spec/AUDIT_VERDICT.json` and post PR review comments with structured verdicts (`CLEAN` or `NEEDS CHANGES`).
3. Never commit or push directly to `main`.
4. Complete slices using `node .harness/scripts/finish-slice.mjs "<msg>"` so Neutral Referee trailers are attached. Run `node .harness/scripts/pr-scope-check.mjs` before PR merges.
5. Do not start a new slice while origin has the tag `harness-main-red` (`git ls-remote --tags origin harness-main-red` prints a line). Fixing main is the only work until it is gone. If repeated build/test failures trigger the 2-strike circuit breaker, restore files with `node .harness/hooks/pre-tool-guard.mjs --restore`.
6. Never merge a PR with a red or missing check.
7. Queue baton-pass updates via `HARNESS_ACTOR=antigravity node .harness/scripts/status-batch.mjs append baton_pass "<summary>"`, and when asked to brief the operator (`"brief me"`), consolidate `node .harness/scripts/status-batch.mjs digest` in plain English using a lightweight Flash/Flash-Lite agent and run `node .harness/scripts/status-batch.mjs clear`.
<!-- <<< harness <<< -->
