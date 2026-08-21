# core/ — Python Core Engine

Scoped context. Read root `CLAUDE.md` and `docs/ARCHITECTURE.md` first — this file only adds local conventions.

## Responsibility

Implements the core-engine verbs from `docs/ARCHITECTURE.md` §2: routing, policy, audit, memory, verify, spec engine, tool registry, diagnostics. **Zero domain-specific logic** — see root `CLAUDE.md` goal 1. If a change references a specific language, framework, cloud provider, or industry, it belongs in a pack, not here.

## Layout (target — grows phase by phase, don't pre-create empty modules)

```
core/
  config/          resolve.py (§4 config layering), defaults.yaml
  routing/         route_request, catalog loader, RAM watchdog        (Phase 1)
  policy/          check_policy, grant_jit_permission, undo buffer     (Phase 3)
  audit/           record_audit, hash-chain, verification              (Phase 3)
  memory/          query_memory, rank_context, hybrid retrieval        (Phase 4)
  verify/          verify_output, failure ledger                       (Phase 2)
  spec/            spec engine (specify/plan/tasks/implement/verify)   (Phase 5)
  packs/           pack loader, manifest validation, capability grant  (Phase 8)
  diagnostics/     run_diagnostics, generate_support_bundle, redact.py (Phase 0/3)
  models/          SQLAlchemy 2.0 models (Postgres-clean from day one)
  migrations/      Alembic
```

## Conventions

- Pydantic v2 models for every verb's input/output — this is the typed contract packs and the gateway depend on. Breaking a verb's schema is a semver-major event (`docs/MAINTENANCE.md` §5).
- Every verb call is auditable: wrap with `record_audit` at the boundary, not scattered inline — one decorator/middleware, not N call sites (mirrors the single-redaction-path rule in `MAINTENANCE.md` §3).
- SQLite in dev, schema written so a Postgres `DATABASE_URL` swap requires zero model changes (no SQLite-only types).
- TDD: `superpowers:test-driven-development` for every verb — failing test in `core/tests/` before implementation.
- No verb reads a config file directly — always through `core/config/resolve.py`.

## What NOT to put here

- Language/stack conventions → `packs/registry/stack-*`
- Cloud/IaC generation logic → `packs/registry/cloud-*`
- Any persona/prompt content → a pack's `personas/`
