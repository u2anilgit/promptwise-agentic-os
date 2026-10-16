# Spec Engine v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `core/spec/` on a new SQLAlchemy/Alembic persistence layer, where a task only reaches `done` after a frozen, unmodified, grounded acceptance check passes, and `converge_feature` detects real drift.

**Architecture:** `core/db/` (engine, session, programmatic Alembic migrate) is the only persistence layer new code uses. `core/spec/` = pure EARS validator + Pydantic contract + SQLAlchemy tables/repository + engine verbs. The engine reuses `orchestrate_tasks` (callable tasks), `verify_output` (gate) and `run_command` (acceptance checks) unchanged, plus one additive field, `VerifyResult.grounded`.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2.0, Alembic. Existing: pytest.

**Spec:** `docs/superpowers/specs/2026-10-16-spec-engine-v2-design.md` (amends `2026-08-31-spec-engine-design.md`; the 2026-08-31 plan's Task 2 `ears.py` is reused as written, its Tasks 1, 3–6 are superseded by Tasks 2–6 below).

## Global Constraints

- Core stays domain-agnostic — no language/framework/test-runner names in `core/spec/` or `core/db/`.
- No module reads config files directly — only via `core/config/resolve.py` (`resolve_config_auto`, `resolve_path`).
- Every engine verb calls `record_audit(actor="spec_engine", action=<stage>, target=<spec_id>, result="allow"|"deny"|"error", detail={..., "artifact_sha256": ...})`. `AuditRecord.result` has no "success".
- Out-of-order stage calls raise `ValueError`; every runtime failure (check fails, check file changed) is a returned result, never an exception.
- Portable SQL only (no SQLite-only types or functions) so `database.url` can point at Postgres.
- TDD: failing test first, run it, then implement. Commit per task, Conventional Commits, **no AI-attribution trailers**.
- Tests use `tmp_path` DB URLs and audit paths; never the repo's `.promptwise/`. Real tiny commands (`python -c "..."`) as acceptance checks, no mocking of `orchestrate_tasks`/`verify_output`.
- Verbatim values: config keys `database.url`, `spec.allow_ungrounded` (default `false`), `spec.trivial_max_requirements` (default `1`); requirement ids `R1`, `R2`, …; error reason strings `acceptance_check_modified`, `acceptance_check_failed`, `ungrounded_verification`, `verify_gate_failed`, `dependency_not_done`.

## Review Focus

1. `verify.test_command` empty → gate "passes" with nothing run → must surface as `ungrounded_verification`, never `done` (Task 0, Task 5).
2. An acceptance-check file deleted or edited after freeze → `acceptance_check_modified`, task stays pending (Task 5).
3. `complexity="trivial"` with 2+ requirements, or with no acceptance check → rejected with `ValueError`, never silently accepted (Task 4).
4. An acceptance-check command that hangs or isn't found → failed check result, no exception, no hang past the runner timeout (Task 5).
5. Unknown `spec_id`, and a database already migrated to a *newer* revision than the code knows → clear `ValueError` / `db.schema` FAIL, not a stack trace (Tasks 1, 4).

---

### Task 0: `VerifyResult.grounded`

**Files:**
- Modify: `core/verify/models.py` (add `grounded: bool = False` to `VerifyResult`), `core/verify/gate.py` (set it)
- Test: `core/tests/verify/test_gate.py`

**Interfaces:**
- Consumes: existing `verify_output(...) -> VerifyResult`; `ToolRunResult.ran`.
- Produces: `VerifyResult.grounded: bool` — `True` iff the test runner's `ToolRunResult.ran` is `True` (a configured test command actually executed).

- [ ] **Step 1: Write failing tests** `test_verify_output_is_ungrounded_when_no_test_command_is_configured` (config `verify.test_command: ""` → `passed is True`, `grounded is False`) and `test_verify_output_is_grounded_when_the_test_command_ran_and_passed` (`test_command: python -c "pass"` → `grounded is True`) plus `..._ungrounded_when_tests_fail` (`passed is False`, `grounded is True`).
- [ ] **Step 2: Run** `python -m pytest core/tests/verify/test_gate.py -q -k grounded` — expected FAIL (attribute missing).
- [ ] **Step 3: Implement** `grounded=test_result.ran` in the `VerifyResult(...)` return; field default `False`.
- [ ] **Step 4: Run** the same command plus `python -m pytest core/tests/verify gateway -q` — expected all PASS.
- [ ] **Step 5: Commit** `feat(verify): report whether a verification pass was grounded in a real test run`.

### Task 1: `core/db/` persistence foundation + `db.schema` doctor check

**Files:**
- Create: `core/db/__init__.py`, `core/db/base.py`, `core/db/migrate.py`, `core/migrations/env.py`, `core/migrations/script.py.mako`, `core/migrations/versions/0001_baseline.py` (empty baseline revision), `core/tests/db/__init__.py`, `core/tests/db/test_db.py`
- Modify: `pyproject.toml` (add `sqlalchemy>=2.0,<3`, `alembic>=1.13`; add `core.migrations` script/package-data), `core/config/defaults.yaml` (`database: {url: ""}` — empty means default file), `core/diagnostics/checks.py`, `core/tests/diagnostics/test_checks.py` (add `"db.schema"` to the expected name set)

**Interfaces:**
- Produces:
  - `class Base(DeclarativeBase)` in `core.db.base`.
  - `make_engine(config: dict, root: Path | None = None) -> Engine` — URL from `database.url`, else `sqlite:///<resolve_path(config,"database.path",".promptwise/agentic.sqlite3",root)>`; on SQLite sets `PRAGMA journal_mode=WAL`, `foreign_keys=ON`, busy timeout 30s.
  - `session_scope(config: dict, root: Path | None = None) -> ContextManager[Session]` — commit on success, rollback on error, always close.
  - `migrate_to_head(config: dict, root: Path | None = None) -> str` returns the resulting revision id.
  - `current_revision(config, root=None) -> str | None`, `head_revision() -> str`.
  - doctor check `db.schema`: PASS when current == head; WARN when DB missing/behind ("run `promptwise db upgrade`"); FAIL when the DB's revision is unknown to this code (newer).
- [ ] **Step 1: Write failing tests:** `test_make_engine_uses_database_url_override`, `test_session_scope_rolls_back_on_error`, `test_migrate_to_head_from_empty_db_reaches_head`, `test_current_revision_none_before_migrate`, `test_db_schema_check_pass_warn_fail` (empty→WARN, migrated→PASS, stamp an unknown revision → FAIL), `test_sqlite_pragmas_applied`.
- [ ] **Step 2: Run** `python -m pytest core/tests/db -q` — expected FAIL (module missing).
- [ ] **Step 3: Implement** as above. Alembic is driven by an in-code `alembic.config.Config()` with `script_location` set to the `core/migrations` path and the resolved URL injected; no `alembic.ini`. `env.py` imports `Base.metadata` and every `core.*.tables` module that exists (so autogenerate sees them).
- [ ] **Step 4: Add CLI** `promptwise db upgrade` (calls `migrate_to_head`, prints revision) in `scripts/promptwise.py` with a test in `scripts/tests/test_cli.py` using a tmp URL.
- [ ] **Step 5: Run** `python -m pytest core/tests/db core/tests/diagnostics scripts -q` — expected PASS.
- [ ] **Step 6: Commit** `feat(db): SQLAlchemy 2 + Alembic persistence foundation with db.schema doctor check`.

### Task 2: `core/spec/models.py` and `ears.py`

**Files:**
- Create: `core/spec/__init__.py`, `core/spec/models.py`, `core/spec/ears.py`, `core/tests/spec/__init__.py`, `core/tests/spec/test_models.py`, `core/tests/spec/test_ears.py`

**Interfaces:**
- Produces (Pydantic v2):
  - `Requirement{id: str, text: str}`; `AcceptanceCheck{requirement_id: str, command: str, files: list[str] = []}`; `FrozenCheck(AcceptanceCheck){file_hashes: dict[str, str]}`.
  - `TaskNode{id, depends_on: list[str] = [], requirement_ids: list[str] = [], expected_symbols: list[str] = [], run: Callable[[dict], Any] | None = None, task_type: str = "general"}` (`arbitrary_types_allowed`).
  - `SpecArtifact{spec_id, request, complexity: Literal["trivial","standard"], requirements: list[Requirement], created_at: float}`; `PlanArtifact{spec_id, approach, created_at}`.
  - `Stage = Literal["specified","planned","tasked","implementing","verified"]`.
  - `EarsViolation{requirement_id, shape_expected, reason}`; `ConvergeReport{spec_id, planned_tasks, done_tasks, pending_tasks, stale: bool, reasons: list[str]}`; `TaskStatus = Literal["pending","done","error"]`.
  - `validate_ears(requirements: list[Requirement]) -> list[EarsViolation]` — the five shapes in the 2026-08-31 design Ruling 4; warnings only.
- [ ] **Step 1: Write failing tests** for each model's required fields/defaults and for `validate_ears` with a known-good and known-bad string for each of the five shapes (Ubiquitous, "When…", "While…", "If…, then…", "Where…"), plus an empty list → `[]`.
- [ ] **Step 2: Run** `python -m pytest core/tests/spec -q` — expected FAIL.
- [ ] **Step 3: Implement** both modules; `validate_ears` is a pure keyword/regex function (reuse the shapes verbatim from the 2026-08-31 design).
- [ ] **Step 4: Run** the same command — expected PASS.
- [ ] **Step 5: Commit** `feat(spec): typed contract and EARS structural validator`.

### Task 3: `core/spec/tables.py` + repository + migration `0002`

**Files:**
- Create: `core/spec/tables.py`, `core/spec/store.py`, `core/migrations/versions/0002_spec_engine.py`, `core/tests/spec/test_store.py`

**Interfaces:**
- Consumes: `Base`, `session_scope`, `migrate_to_head` (Task 1); models (Task 2).
- Produces tables `spec`, `spec_requirement`, `plan`, `task` (`spec_id`, `task_id`, `status`, `requirement_ids` JSON, `depends_on` JSON, `expected_symbols` JSON, `interactive: bool`, `error`), `acceptance_check` (`spec_id`, `requirement_id`, `command`, `files` JSON, `file_hashes` JSON, `frozen_at`), `spec_stage` (`spec_id` PK, `stage`). Repository functions, each taking a `Session`: `save_spec`, `get_spec -> SpecArtifact | None`, `get_stage -> Stage | None`, `set_stage`, `save_plan`, `get_plan`, `save_tasks(spec_id, list[TaskNode])`, `get_tasks(spec_id) -> list[TaskRow]`, `set_task_status(spec_id, task_id, status, error=None)`, `save_frozen_checks(spec_id, list[FrozenCheck])`, `get_frozen_checks`, `replace_frozen_check(spec_id, requirement_id, FrozenCheck) -> FrozenCheck` (returns the old one).
- [ ] **Step 1: Write failing tests:** round-trip of each entity; `get_spec("nope") is None`; `replace_frozen_check` returns the previous row; the migration upgrades an empty DB to include these tables (inspect via `sqlalchemy.inspect`); `spec_stage` rejects a duplicate PK.
- [ ] **Step 2: Run** `python -m pytest core/tests/spec/test_store.py -q` — expected FAIL.
- [ ] **Step 3: Implement** tables with portable types (`String`, `Integer`, `Float`, `Boolean`, `JSON`); write migration `0002` by hand (do not rely on autogenerate output unreviewed); `down_revision = "0001"`.
- [ ] **Step 4: Run** the test file plus `python -m pytest core/tests/db -q` — expected PASS.
- [ ] **Step 5: Commit** `feat(spec): SQLAlchemy tables, repository and migration for spec artifacts`.

### Task 4: engine — `specify_feature`, `plan_feature`, `tasks_feature` (freeze)

**Files:**
- Create: `core/spec/engine.py`, `core/tests/spec/test_engine_stages.py`

**Interfaces:**
- Consumes: Tasks 0–3; `orchestrate_tasks`, `topological_order`, `record_audit`.
- Produces:
  - `specify_feature(request: str, requirements: list[str], complexity="standard", config=None, root=None) -> SpecResult{spec_id, requirements: list[Requirement], violations: list[EarsViolation]}` — assigns `R1…`, validates EARS (warnings only); `trivial` requires `len(requirements) <= spec.trivial_max_requirements` else `ValueError`; audits `complexity_declared`.
  - `plan_feature(spec_id, approach, ...) -> PlanArtifact` — requires stage `specified`.
  - `tasks_feature(spec_id, tasks: list[TaskNode], checks: list[AcceptanceCheck], ...) -> TasksResult{frozen: list[FrozenCheck], automated: DagResult | None}` — requires `planned` (or `specified` when trivial: auto-plans and auto-creates one implicit task if `tasks` empty); every requirement id must have ≥ 1 check, every `requirement_ids` entry must exist, callable tasks may only depend on callable tasks (carried from the 2026-08-31 plan), DAG validated with `topological_order`; hashes every check file (sha256 of bytes; a missing file raises `ValueError`); runs callable tasks through unchanged `orchestrate_tasks`, marking results in the store; stage → `tasked`.
  - Every audit entry's `detail.artifact_sha256` = sha256 of the canonical JSON of the artifact just written.
- [ ] **Step 1: Write failing tests** (one assertion focus each): ids assigned `R1,R2`; EARS violation reported but not raised; out-of-order `plan_feature` → `ValueError`; unknown `spec_id` → `ValueError("unknown spec")`; trivial with 2 requirements → `ValueError`; trivial still demands a check → `ValueError` when `checks` empty; requirement with no check → `ValueError`; missing check file → `ValueError`; hashes stored equal `sha256` of file bytes; cycle → `ValueError` before anything runs; callable depending on interactive → `ValueError`; callable task executed and stored `done`; audit entry carries `artifact_sha256`.
- [ ] **Step 2: Run** `python -m pytest core/tests/spec/test_engine_stages.py -q` — expected FAIL.
- [ ] **Step 3: Implement** the three verbs; `config=None` resolves via `resolve_config_auto(root)`; each verb opens one `session_scope` and `migrate_to_head`s lazily on first use.
- [ ] **Step 4: Run** `python -m pytest core/tests/spec -q` — expected PASS.
- [ ] **Step 5: Commit** `feat(spec): specify/plan/tasks verbs with frozen acceptance checks`.

### Task 5: engine — `complete_task` and `amend_check`

**Files:**
- Modify: `core/spec/engine.py`
- Create: `core/tests/spec/test_engine_complete.py`

**Interfaces:**
- Consumes: Task 4; `run_command` (`core/verify/runners.py`), `verify_output` + `grounded` (Task 0).
- Produces:
  - `CompletionResult{task_id, accepted: bool, status: TaskStatus, reasons: list[str], verify: VerifyResult | None}`.
  - `complete_task(spec_id, task_id, evidence: str, cwd: Path | None = None, config=None, root=None) -> CompletionResult` — accepted only if all hold, evaluated in this order and short-circuiting with a reason: dependencies done (`dependency_not_done`) → every frozen check for the task's `requirement_ids` has unchanged file hashes (`acceptance_check_modified`; a deleted file counts as modified) → every such check command passes via `run_command` (`acceptance_check_failed`) → `verify_output(diff=evidence, cwd=cwd)` passes (`verify_gate_failed`) → `verify.grounded` or `spec.allow_ungrounded` (`ungrounded_verification`). On accept: task `done`, stage `implementing`. Never raises for check/gate failures; unknown spec/task → `ValueError`.
  - `amend_check(spec_id, requirement_id, new_check: AcceptanceCheck, reason: str, config=None, root=None) -> FrozenCheck` — re-hashes, stores, audits `action="amend_check"` with old and new hashes and `reason`; empty `reason` → `ValueError`.
- [ ] **Step 1: Write failing tests** using a real tmp project: check file `check.py` containing `import sys; sys.exit(0)` (and a failing variant); edit the file after freeze → `acceptance_check_modified`; delete it → same; `amend_check` then `complete_task` accepts; failing check → `acceptance_check_failed`, task stays `pending`; `test_command: ""` → `ungrounded_verification` unless `spec.allow_ungrounded: true`; hanging command (`python -c "import time; time.sleep(60)"` with a 1s timeout through config `verify`-style timeout argument) → `acceptance_check_failed`, test completes in < 10s; unmet dependency → `dependency_not_done`; empty amend reason → `ValueError`.
- [ ] **Step 2: Run** `python -m pytest core/tests/spec/test_engine_complete.py -q` — expected FAIL.
- [ ] **Step 3: Implement** both verbs; acceptance-check timeout reads `spec.check_timeout_seconds` (default `300`) and is passed to `run_command(timeout=...)`.
- [ ] **Step 4: Run** `python -m pytest core/tests/spec -q` — expected PASS.
- [ ] **Step 5: Commit** `feat(spec): complete_task gates on frozen, grounded acceptance checks; audited amend_check`.

### Task 6: engine — `verify_feature` and `converge_feature`

**Files:**
- Modify: `core/spec/engine.py`
- Create: `core/tests/spec/test_engine_converge.py`

**Interfaces:**
- Consumes: Tasks 4–5; `query_code_index` (`core/index/query.py`) for `expected_symbols`.
- Produces:
  - `verify_feature(spec_id, config=None, root=None) -> VerifyFeatureResult{spec_id, verified: bool, outstanding: list[str], uncovered_requirements: list[str]}` — `verified` only if every task `done` and every requirement is covered by ≥ 1 done task; stage → `verified` only then; never raises for incompleteness.
  - `converge_feature(spec_id, config=None, root=None) -> ConvergeReport` — read-only; `reasons` drawn from: `requirements_changed` (current requirements hash ≠ hash recorded at `plan`), `check_file_changed:<path>`, `check_file_missing:<path>`, `requirement_uncovered:<Rn>`, `symbol_missing:<name>`; `stale = bool(reasons)`. Counts: `planned_tasks`, `done_tasks`, `pending_tasks`.
- [ ] **Step 1: Write failing tests**, one per reason string above plus: all-done+covered → `verified True`; one pending → listed in `outstanding`; fresh consistent spec → `stale False`, `reasons == []`; `expected_symbols` present in a tiny tmp Python repo → no reason, absent → `symbol_missing:<name>`; unknown spec → `ValueError`.
- [ ] **Step 2: Run** `python -m pytest core/tests/spec/test_engine_converge.py -q` — expected FAIL.
- [ ] **Step 3: Implement**; requirements hash = sha256 of canonical JSON of `[(id, text)]`, recorded in the audit `detail` at `plan_feature` time and persisted in the `plan.requirements_sha256` column Task 3 already creates.
- [ ] **Step 4: Run** the full suite `python -m pytest -q` — expected all PASS.
- [ ] **Step 5: Docs + commit:** update `docs/ROADMAP.md` (Phase 5.2 status), `CLAUDE.md` status, `docs/BACKLOG.md` (MCP exposure of the six spec verbs + `promptwise spec` CLI remain), and `docs/ARCHITECTURE.md` §2 if it lists `core/spec/`; commit `feat(spec): verify_feature and hash-based converge drift detection`.

## Self-Review

- **Spec coverage:** Ruling 5 → Tasks 1, 3; Ruling 6 → Tasks 0, 4, 5; Ruling 7 → Task 6; Ruling 8 → Task 4; Ruling 9 → Task 4 (artifact hash in audit; carried by every verb); the four original problems → Tasks 0, 5, 6, 1.
- **Interface consistency:** `FrozenCheck`/`AcceptanceCheck` fields identical in Tasks 2–6; `Stage` literals identical; reason strings match Global Constraints.
- **Known coupling:** Task 6's `requirements_changed` reads `plan.requirements_sha256`, which Task 3 creates and Task 4's `plan_feature` writes.
- **Not covered, deliberately:** MCP exposure, `promptwise spec` CLI, mutation/second-model verification, migrating existing stores (all logged as follow-ups).
