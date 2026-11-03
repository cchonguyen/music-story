# SESSION HANDOFF (updated 2026-11-03, after the docs consolidation)
- **Active Branch / State:** `claude/project-thread-rn4mga`. Docs consolidation: `CLAUDE.md` is a shim, rules in `docs/RULES.md`, Context Atlas registry in `.spec/ATLAS.md`.
- **Real-data build:** done 2026-11-03 on Charlie's Mac (`build_pipeline --from 03`, `genre unmapped` exit 0, site build exit 0). Deployed the same day; `music.charliechonguyen.com` returns 302 to Access. Details in `STATE.md`.
- **Harness-main-red:** `git ls-remote --tags origin harness-main-red` returned no tag on 2026-11-03, so no block is in force. The earlier "main is red" note was stale.
- **Size watch:** `explorer` (19.2 MB) and `genres` (19.4 MB) are under the 25 MB limit. Check them before the next deploy.
- **Next step:** open items in `docs/PROJECT.md` section 8. Nothing is in progress.
