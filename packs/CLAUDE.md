# packs/ — Skill/Intelligence Pack Authoring

Scoped context. Read root `CLAUDE.md` and `docs/ARCHITECTURE.md` §3 (Pack Contract) first — this file is the practical authoring checklist, not the design rationale.

## Directory roles

- `registry/` — source of truth for every pack this repo ships or references. A pack lives here whether or not any deployment has it installed.
- `installed/` — an org's active set, populated by `promptwise pack install`. Gitignored in downstream deployments; this repo may seed a few reference packs here for local dev only.

## Authoring checklist (every pack, no exceptions)

1. `pack.yaml` — name, version, `kind`, `summary`, `requires_core` semver range, `capabilities` (least privilege — list only what's actually used), `permissions_rationale` (one sentence, human-readable, shown at install-approval time), `dependencies`.
2. `personas/` — system-prompt fragments, one file per role this pack adds. Plain markdown, no code.
3. `verify-rules/` — additional lint/test/security rules layered onto `verify_output` for this domain. Must not weaken any core-shipped rule, only add.
4. `catalog-hints.yaml` — model-tier preferences for this pack's task types (e.g. "SQL generation prefers local-code tier, escalate on schema >50 tables").
5. `dags/` — any `orchestrate_tasks` DAG templates this pack contributes (e.g. a migration pack's analyzer→mapper→converter→test-gen chain).
6. `tools/` — optional. Declarative MCP tool definitions this pack exposes; every one must map to an existing core verb through `check_policy` — a pack tool that touches fs/shell/DB directly fails review.
7. `troubleshooting.md` — **required, not optional**. At least the failure modes you hit while building the pack. Consumed automatically by `promptwise doctor` and the dashboard Diagnostics panel (`docs/MAINTENANCE.md` §4).
8. `CHANGELOG.md` — semver-tagged entries from v1.0.0.

## Review gate for any pack PR

- Does it touch `core/` or `gateway/`? → reject, domain logic belongs here, not there (root `CLAUDE.md` goal 1).
- Does `capabilities` in `pack.yaml` list anything not actually exercised by `tools/` or `dags/`? → reject, tighten to least privilege.
- Is `troubleshooting.md` present with at least one real entry? → reject if missing.
- Does `requires_core` pin a range wide enough to survive the next minor core release, narrow enough to fail loudly on a breaking one? → check against `docs/MAINTENANCE.md` §5 deprecation policy.

## Reference packs planned for Phase 8

3 stack packs (pick your own daily stacks first — Python/FastAPI is the obvious first given the core's own stack), 1 database pack, 1 cloud/CI-CD pack, 1 architecture-advisor pack. See `docs/ROADMAP.md` Phase 8 acceptance criteria.
