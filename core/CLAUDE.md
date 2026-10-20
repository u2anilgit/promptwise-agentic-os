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
  actions/         fs_write: the governed action layer (policy-gated, audited, undo-buffered) (Phase 3)
  audit/           record_audit, hash-chain, verification              (Phase 3)
  memory/          query_memory, rank_context, hybrid retrieval        (Phase 4)
  index/           query_code_index: tree-sitter definitions, SQLite symbol store (Phase 4)
  ingestion/       run_ingestion_sweep (index refresh + session facts)  (Phase 4)
  orchestrate/     topological_order, orchestrate_tasks DAG runner     (Phase 5)
  verify/          verify_output, failure ledger                       (Phase 2)
  spec/            spec engine: specify/plan/tasks(freeze)/complete_task/verify/converge   (Phase 5, done)
  packs/           pack loader, manifest validation, capability grant  (Phase 8)
  diagnostics/     run_diagnostics, generate_support_bundle, redact.py (Phase 0/3)
  db/              SQLAlchemy 2.0 Base/engine/session_scope, programmatic Alembic (new durable state only)
  security/        supply_chain (deny-list + lockfile), untrusted-content tagging
  migrations/      Alembic revisions (0001 baseline, 0002 spec engine, 0003 baselines, 0004 usage ledger)
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
