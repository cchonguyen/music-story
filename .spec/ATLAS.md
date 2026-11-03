# Context Atlas (registry)

Rules: `docs/CONTEXT_ATLAS.md`. Sectors 000–400 are harness; 500 is project. Read on demand only.

## Sector 000 Card Catalog
- `000` [AGENTS.md](AGENTS.md) — agent contract and harness card catalog
- `001` [CLAUDE.md](CLAUDE.md) — shim: start point and imports

## Sector 100 Work Dispatch
- `110` [.spec/PROGRESS.md](.spec/PROGRESS.md) — active slices for the current wave
- `120` [.spec/archive/HISTORY.md](.spec/archive/HISTORY.md) — completed slices

## Sector 200 Boundaries
- `210` [.spec/boundaries/locks.md](.spec/boundaries/locks.md) — which files a slice may edit
- `220` [.spec/boundaries/do-not-build.md](.spec/boundaries/do-not-build.md) — out-of-scope list

## Sector 300 Contracts
- `305` [.harness/config/thresholds.json](.harness/config/thresholds.json) — budgets and breaker limits
- `310` [.spec/contracts/referee.md](.spec/contracts/referee.md) — verification and trailers
- `320` [.spec/contracts/circuit-breaker.md](.spec/contracts/circuit-breaker.md) — two-strike stop
- `330` [.spec/contracts/baton-pass.md](.spec/contracts/baton-pass.md) — session handoff fields
- `340` [.spec/contracts/review-relay.md](.spec/contracts/review-relay.md) — audit verdicts

## Sector 400 System Spec
- `400` [.spec/SYSTEM_SPEC.md](.spec/SYSTEM_SPEC.md) — scope, invariants, module boundaries

## Sector 500 Project
- `510` [STATE.md](STATE.md) — wave, packet status, next steps
- `520` [docs/PROJECT.md](docs/PROJECT.md) — data facts, pipeline, decisions, open items
- `530` [docs/RULES.md](docs/RULES.md) — working rules, layout, commands, deploy
- `540` [sql/schema.sql](sql/schema.sql) — table contract
- `550` [specs/](specs/) — one spec per work packet
- `560` [site/](site/) — Observable Framework site
