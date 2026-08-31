# Design: Spec Engine — `specify/plan/tasks/implement/verify` (Phase 5 sub-project 2 of 2)

**Date:** 2026-08-31
**Status:** approved by user 2026-08-31 (design approved; implementation planning next via writing-plans)
**Depends on:** `core/orchestrate/` (sub-project 1, merged `9fe587d`), `core/verify/` (Phase 2), `core/audit/` (Phase 3), `core/config/resolve.py`.
**Research grounding:** `docs/research/2026-08-31-findings-refresh.md` §2 (SDD critique), §6 (action items).

## Problem

`docs/ROADMAP.md`'s Phase 5 acceptance criterion: *"`specify → plan → tasks → implement → verify` runs end-to-end on one real feature request, produces EARS-format artifacts, and the `implement` step's output must pass Phase 2's gate before `verify` marks it done."* `docs/ARCHITECTURE.md` §2 says the spec engine wraps `orchestrate_tasks`. Neither doc specifies who actually writes the code during `implement` — resolved below (Ruling 1).

## Non-goals

- Core does not invoke an LLM/agent to generate spec/plan/task content — no LLM client exists anywhere in `core/` (confirmed, `docs/research/2026-08-31-findings-refresh.md` §0). The calling agent (Claude Code, etc.) authors the content; the engine validates structure and enforces ordering/gating.
- EARS validation is structural (pattern/keyword check for the 5 canonical shapes), not semantic/NLP quality scoring.
- No declarative pack-provided spec templates this pass — a natural follow-up once a real pack needs one (same deferral pattern as `orchestrate_tasks`'s declarative-DAG loading).
- No retry/backoff policy for a failed task — matches `orchestrate_tasks`'s existing precedent (failure is reported, retry is a caller concern).

## Ruling 1 (the crux decision): hybrid task execution — automatable via `orchestrate_tasks`, interactive via `complete_task`

**Decision:** `tasks_feature(plan_id)` returns a `Dag` (reusing `core/orchestrate/models.py`'s `Dag`/`DagNode` unchanged) of `TaskNode`s. A node with a `run` callable supplied (scriptable work — scaffolding, codegen, a lint/fix script) is executed by calling the *existing, unmodified* `orchestrate_tasks()`. A node with no callable is "interactive" — its status starts `"pending"` and only advances to `"done"` when the calling agent invokes `complete_task(task_id, evidence)` after doing the actual implementation work itself (via the agent's own turns, using already-governed tools like `fs_write`). `complete_task` internally calls `verify_output` (Phase 2) before accepting the task as done — this is the literal mechanism satisfying the ROADMAP criterion "`implement` step's output must pass Phase 2's gate before `verify` marks it done." `core/orchestrate/graph.py`'s `topological_order()` is reused directly (unchanged) to gate dependents of either task kind identically — an interactive task's dependents don't unblock until `complete_task` marks it done, exactly like a callable-executed node.

**Why:** `orchestrate_tasks()` runs synchronously start-to-finish within one call (Ruling 1 of its own design doc: sequential, no concurrency) — it cannot itself "pause" mid-DAG waiting for a multi-turn interactive agent to write real code without hanging the tool call. Real feature implementation is exactly the kind of work `orchestrate_tasks`' own Ruling 2 already excludes core from doing (no LLM/agent-invocation client exists). This hybrid keeps `orchestrate_tasks` genuinely reused (not just referenced) for the subset of tasks that *are* expressible as plain callables, while the majority — actual code-writing — stays agent-driven, consistent with every other core verb in this repo.

**Cost if wrong:** if most real tasks turn out to be automatable after all, the interactive path becomes a fallback rather than the common case — no structural change needed, `TaskNode.run` being optional already supports both from day one.

## Ruling 2 (ceremony scaling): `complexity` flag skips plan/tasks for trivial work

**Decision:** `specify_feature(request: str, complexity: Literal["trivial", "standard"] = "standard")`. When `complexity="trivial"`, the engine auto-generates a single implicit `TaskNode` (no separate `plan_feature`/`tasks_feature` calls needed) and the caller proceeds directly to `complete_task` → `verify_feature`. `complexity="standard"` requires the full `specify → plan → tasks` sequence before any task can be worked.

**Why:** the single most-corroborated SDD failure pattern found in research (`2026-08-31-findings-refresh.md` §2, Fowler/Böckeler critique) is spec ceremony exceeding its value for small changes — "a sledgehammer to crack a nut." This repo's own `CLAUDE.md:68` already carves out an equivalent exception for `writing-plans` (bounded fixes skip straight to inline edit); this ruling applies the same principle inside the spec engine itself rather than only at the meta-level of "should I even use the spec engine."

**Cost if wrong:** a genuinely complex request mis-flagged `trivial` skips useful structure — mitigated by `complete_task`'s `verify_output` gate still applying regardless of complexity (the safety net doesn't shrink, only the up-front ceremony does).

## Ruling 3 (anti-drift): `converge_feature` reports drift, doesn't re-verify

**Decision:** `converge_feature(spec_id) -> ConvergeReport{planned_tasks, done_tasks, pending_tasks, stale: bool}` diffs the plan's task list against current completion state. It does not re-run `verify_output` itself (that stays `complete_task`'s job) — it only surfaces "plan says N tasks, M are done" so a stale/drifted spec is visible rather than silently ignored.

**Why:** the second-most-corroborated SDD failure pattern (spec drift — the spec stops tracking evolving code) has a direct, already-proven fix in the field: GitHub Spec Kit's `/speckit.converge` command (`findings-refresh.md` §2, primary source). This ruling adopts the pattern, not the exact command name.

**Cost if wrong:** none identified — this is a read-only reporting verb, additive to the pipeline.

## Ruling 4 (EARS validation scope): structural pattern check only

**Decision:** `ears.py`'s `validate_ears(requirements: list[str]) -> list[EarsViolation]` checks each requirement string against the 5 canonical EARS sentence shapes (Ubiquitous: "The `<system>` shall `<response>`"; Event-driven: "When `<trigger>`, the `<system>` shall `<response>`"; State-driven: "While `<state>`, the `<system>` shall `<response>`"; Unwanted: "If `<condition>`, then the `<system>` shall `<response>`"; Optional: "Where `<feature>`, the `<system>` shall `<response>`") via keyword/regex pattern matching — a linter, not a generator or semantic scorer.

**Why:** matches the non-goal above (no LLM in core) and mirrors `core/verify/`'s existing precedent of orchestrating objective, external, mechanically-checkable signals rather than LLM self-critique (research §1's strongest-evidenced reliability finding — grounded verification beats self-critique).

**Cost if wrong:** a well-formed-but-not-pattern-matching requirement gets flagged as a violation (false positive) — `specify_feature` reports violations as warnings, does not block on them (a caller can proceed with an acknowledged violation; matches this repo's general fail-open-with-visibility discipline).

## Architecture

```
core/spec/
  __init__.py
  models.py    SpecArtifact{spec_id, request, complexity, requirements: list[str], created_at}
               PlanArtifact{spec_id, plan_id, approach, created_at}
               TaskNode(DagNode subclass shape — adds nothing to the field set, `run: Callable|None`
                         already optional on the base DagNode)
               SpecState{spec_id, stage: Literal["specified","planned","tasked","implementing",
                         "verified"], task_dag: Dag|None}
               EarsViolation{requirement: str, shape_expected: str, reason: str}
               ConvergeReport{spec_id, planned_tasks: int, done_tasks: int, pending_tasks: int,
                               stale: bool}
  ears.py      validate_ears(requirements) -> list[EarsViolation] — pure function, no I/O.
  store.py     SQLite-backed artifact store (same pattern as core/index, core/memory) — one row
               per spec_id/stage, `SpecStore.save_spec/save_plan/save_tasks/get_state`.
  engine.py    specify_feature, plan_feature, tasks_feature, complete_task, verify_feature,
               converge_feature — the public verbs, all going through core/config/resolve.py,
               all record_audit'd.
```

## Data flow

1. `specify_feature(request, complexity="standard")` → validates requirements via `ears.py` (warnings only), stores a `SpecArtifact`, returns `spec_id` + any `EarsViolation`s. State → `"specified"`.
2. `plan_feature(spec_id, approach)` → requires state `"specified"` (else `ValueError`, same convention as `orchestrate_tasks`'s structural-error precedent), stores a `PlanArtifact`. State → `"planned"`.
3. `tasks_feature(spec_id, tasks: list[TaskNode])` → requires state `"planned"` (or is auto-invoked internally for `complexity="trivial"` with a single implicit task). Builds a `Dag`, calls `topological_order()` to validate the caller-supplied dependency graph up front (raises immediately on cycle/dangling ref, same as `orchestrate_tasks`). Runs any callable-bearing nodes via `orchestrate_tasks()` unchanged. State → `"tasked"` → `"implementing"`.
4. `complete_task(spec_id, task_id, evidence)` → for each interactive task the agent finishes: calls `verify_output(evidence)` (Phase 2); on pass, marks the task `"done"` in the stored `Dag`'s results, unblocking dependents per `topological_order()`; on fail, task stays `"pending"`, violation surfaced to caller, nothing silently marked done.
5. `verify_feature(spec_id)` → requires all tasks `"done"` (else reports which are outstanding, does not raise — matches fail-open-with-visibility). On all-done, state → `"verified"`.
6. `converge_feature(spec_id)` → callable any time after `"tasked"`, read-only drift report (Ruling 3).

Every verb call is `record_audit`'d (actor=`"spec_engine"`, action=stage name, target=`spec_id`), same convention as `orchestrate_tasks`.

## Error handling

- Out-of-order stage call → `ValueError` immediately, caller error (same precedent as `orchestrate_tasks`'s cycle/dangling-reference check).
- Malformed task DAG (cycle, dangling dependency) → `ValueError` immediately via reused `topological_order()`, before any task starts.
- A callable-executed task's failure → reported via `orchestrate_tasks()`'s existing `DagResult` (status `"error"`), does not abort the rest of the DAG (Ruling 4 of the orchestrate-tasks design, inherited unchanged).
- `complete_task` called with evidence that fails `verify_output` → task stays `"pending"`, violation returned to caller, never silently marked done.
- EARS violations → warnings, non-blocking (Ruling 4 above).

## Testing

TDD per module (repo convention, `CLAUDE.md:67`):
- `ears.py`: pure-function tests against known-good/known-bad strings for all 5 shapes.
- `store.py`: temp-SQLite-backed tests, same pattern as `core/index`/`core/memory`'s existing test suites.
- `engine.py`: stage-ordering enforcement (`ValueError` on out-of-order calls), the hybrid execution path (one test with only callable tasks, one with only interactive tasks via `complete_task`, one mixed), `converge_feature`'s drift detection, `complexity="trivial"` shortcut path. No mocking of `orchestrate_tasks`/`verify_output` — both already independently unit-tested; engine tests use real instances (repo's DI-over-monkeypatching convention, `CLAUDE.md`/prior specs' established pattern).

## Global constraints (carried forward, still binding)

- Core stays domain-agnostic — no pack-specific branching in `core/spec/`.
- No verb reads a config file directly — always through `core/config/resolve.py`.
- Pydantic v2 models for the typed contract.
- Every verb call is auditable via `record_audit`.
- Never crash on malformed input past the structural-validity checks; degrade node-by-node past that point.

## Out of scope (deliberately)

- LLM-generated spec/plan/task content (non-goal above).
- Declarative pack-provided spec templates (follow-up, not speculative now).
- Retry/backoff policy for failed tasks (caller concern, matches `orchestrate_tasks` precedent).
- MCP tool exposure for these verbs — this spec covers the `core/spec/` verbs only; wiring them into `gateway/`'s MCP server is a fast-follow, same deferral pattern `orchestrate_tasks`' own design doc used for its own MCP exposure.
- Parallel task execution — inherits `orchestrate_tasks`' sequential-only Ruling 1 unchanged.

## Post-plan follow-ups (log to `docs/BACKLOG.md` if not picked up immediately)

- MCP tool exposure for all six `core/spec/` verbs.
- Declarative task templates from a pack's future `dags/` or `specs/` folder.
- Revisit `orchestrate_tasks`' open BACKLOG item (`route_request` call outside per-node `try`) before/alongside this work, since `tasks_feature` calls it directly for the automatable subset.
- SQLAlchemy/Alembic persistence gap flagged in `2026-08-31-findings-refresh.md` §0 — `core/spec/store.py` as specified here uses the same ad-hoc SQLite pattern as `core/index`/`core/memory`, consistent with current repo convention, but this is the third module now on that pattern ahead of any real ORM/migrations layer — worth resolving before a fourth.
