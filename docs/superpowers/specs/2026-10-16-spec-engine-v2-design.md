# Design: Spec Engine v2 — persistence, independent verification, real drift detection

**Date:** 2026-10-16
**Status:** decisions made by assistant under the user's explicit "go ahead with your best recommendation" (2026-10-16); user to review. Amends — does not replace — `2026-08-31-spec-engine-design.md` (Rulings 1, 2 and 4 there stand; Ruling 3 and the storage section are superseded as noted below).
**Grounding:** `docs/research/2026-10-16-agent-landscape-gap-analysis.md` (pain points 7, 8, 9; Phase 3.5), `docs/IMPLEMENTATION_ANALYSIS.md` F-01/F-02.

## Why v2

Checking the 2026-08-31 plan against the 2026-10 gap analysis found four holes that would make the spec engine rubber-stamp work:

1. **Vacuous verification.** `core/verify/runners.py:run_command` returns `ran=False, passed=True` when `verify.test_command` is empty, so `verify_output` — and therefore the original `complete_task` — can "verify" a task having run zero tests. The product's headline guarantee would be satisfiable by doing nothing.
2. **Self-attested checks.** The agent that implements a task also writes (or edits) the tests that judge it. Passing proves only the agent agrees with itself.
3. **Cosmetic drift detection.** The original `converge_feature` counted done/pending tasks. It could not notice that requirements changed after planning, that an acceptance check was edited, or that code the plan relied on no longer exists.
4. **A third ad-hoc SQLite store** on a locked-stack item (SQLAlchemy/Alembic) that has no code at all.

## Goals / non-goals / anti-goals

- **Goal:** a task cannot reach `done` unless an acceptance check that was *frozen before implementation* ran and passed.
- **Goal:** drift between spec, frozen checks and code is detected and reported, not inferred from task counts.
- **Goal:** one persistence layer (SQLAlchemy 2 + Alembic) all new durable state uses; existing stores migrate opportunistically, not in this project.
- **Non-goal:** core still never calls an LLM; no mutation testing or second-model verifier here (Phase 2 addendum, separate project).
- **Non-goal:** migrating `core/index`, `core/memory`, JSON stores to SQLAlchemy.
- **Anti-goal:** ceremony that makes small changes slower than doing them by hand. The `trivial` path must stay one-call cheap.

## Ruling 5 — Persistence: SQLAlchemy 2.0 + Alembic, new code only

`core/db/` provides: `Base` (DeclarativeBase), `make_engine(config)` (URL from `database.url`, default `sqlite:///<root>/.promptwise/agentic.sqlite3`; WAL + `foreign_keys=ON` on SQLite), `session_scope(config)` context manager, and `migrate_to_head(config)` using Alembic programmatically (scripts under `core/migrations/`, no `alembic.ini`). Types are portable (no SQLite-only types) so a Postgres URL is a config change. A `db.schema` doctor check reports current revision vs head (WARN if behind, FAIL if the DB is newer than the code). `sqlalchemy` and `alembic` become declared dependencies. **Why not keep sqlite3:** it's the third copy of the same pattern, has no migration story, and the locked stack already says otherwise. **Cost if wrong:** low — models are plain declarative classes; the repository layer is the only caller.

## Ruling 6 — Independent verification: acceptance checks are frozen before implementation

- Each requirement gets a stable id (`R1`, `R2`, …) at `specify`.
- At `tasks` time every requirement must have ≥ 1 **acceptance check**: `{requirement_id, command, files[]}` where `command` is an argv string run through the existing `run_command` machinery and `files` are the check's source files (test files, fixtures). The engine records `sha256` of each file at freeze time (`checks_frozen_at`).
- `complete_task` accepts a task as done only if **all** hold: (a) every acceptance check linked to the task's `requirement_ids` re-runs now and passes; (b) none of those checks' files changed since freeze (otherwise `acceptance_check_modified`, task stays pending — changing a check requires an explicit, audited `amend_check` call that records old/new hash and a reason); (c) the `verify_output` gate passes; (d) the gate is **grounded** (below) unless `spec.allow_ungrounded: true`.
- **Grounded:** `VerifyResult` gains `grounded: bool` = the configured test command actually ran. An ungrounded pass is reported as such, never as plain success.
- The engine is domain-agnostic: it only runs configured commands and hashes files; it knows nothing about test frameworks.
- **What this does not claim:** freezing stops silent edits to checks, not badly written checks. Quality of checks is the Phase 2 addendum's job (mutation check / second-model verifier).

## Ruling 7 — Drift: `converge_feature` compares hashes and symbols, not task counts

`ConvergeReport` reports, with reasons: requirements changed since planning (hash of requirement list vs frozen), acceptance-check files changed/missing, requirements with no covering done task, and — optionally, when a task declares `expected_symbols` — symbols no longer found via `query_code_index`. `stale = bool(any reason)`. Read-only; never re-runs checks (that stays `complete_task`'s job). This supersedes Ruling 3 of the 2026-08-31 design.

## Ruling 8 — Complexity flag: ceremony shrinks, the gate does not

`complexity="trivial"` remains (Ruling 2 of the original), with guards: ≤ `spec.trivial_max_requirements` (default 1) requirements, and it still requires one frozen acceptance check and grounded verification. The declaration is audited (`complexity_declared`). A caller cannot use `trivial` to skip verification — only to skip `plan`/`tasks` ceremony.

## Ruling 9 — Artifacts are tamper-evident through the audit chain

Every stage transition `record_audit`s with `detail.artifact_sha256` (hash of the canonical JSON of the spec/plan/task set at that moment). The hash chain then makes later rewriting of an artifact detectable by comparison.

## Architecture delta vs the 2026-08-31 design

```
core/db/            base.py (Base, make_engine, session_scope), migrate.py (migrate_to_head, current/head revision)
core/migrations/    env.py, versions/0001_spec_engine.py
core/spec/
  models.py         + requirement ids, AcceptanceCheck, FrozenCheck, expected_symbols
  ears.py           unchanged from the original plan
  tables.py         SQLAlchemy models (spec, plan, task, acceptance_check)
  store.py          repository functions over a Session (replaces sqlite3 store)
  engine.py         + freeze/amend_check, grounded + frozen-check gating, hash-based converge
core/verify/        VerifyResult.grounded (additive, default-compatible)
core/diagnostics/   db.schema check
```

## Error handling / testing deltas

- `complete_task` on a modified check → `NodeResult`-style rejection with reason, never an exception; stage-order violations still `ValueError`.
- Every ruling gets a failing-test-first: vacuous pass reported as ungrounded; edited check file rejected; amended check audited; drift reasons each reproduced; trivial path still requires a check; Alembic upgrade from empty DB reaches head and `db.schema` reports PASS; SQLite and an in-memory second dialect-neutral smoke (no SQLite-only SQL).
- No mocking of `orchestrate_tasks`/`verify_output`; real instances with a tiny real command (e.g. `python -c`) as the acceptance check.

## Open items left to the builder (my calls, flagged)

- Exact Alembic revision id format and `db.schema` thresholds.
- Whether `amend_check` needs a JIT grant (recommend: yes, reuse `core/policy/jit.py`) — my call: start with audit-only, add JIT in a follow-up.
- MCP exposure of the verbs remains the deferred batch pass.

## Out of scope

Mutation testing / second-model verifier; migrating existing stores; Postgres CI matrix; dashboard views of specs.

## Amendments from the whole-branch review (2026-10-16)

- A check with a blank or unparsable command is rejected at freeze/amend; `ran=False` is never a pass (vacuous-pass hole at the check layer).
- Every task must reference at least one requirement, so no task can reach `done` with zero checks.
- Every check must name at least one file unless `spec.allow_fileless_checks`; the `tasks` audit entry lists requirements whose command does not mention any listed file (`unreferenced_check_files`).
- `amend_check` reopens done tasks linked to the requirement and drops a `verified` spec back to `implementing`.
- Acceptance-check commands are policy-gated as `shell:run:<program>` (default-deny; `spec.enforce_command_policy`, default true) and rejections are audited with `denied_actions`.
- A database revision newer than the code raises a clear `ValueError` from every verb.
- Known limit: Windows backslash paths in check commands fail closed under POSIX `shlex`; use forward slashes.
