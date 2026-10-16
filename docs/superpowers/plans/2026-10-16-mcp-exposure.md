# MCP Exposure of Core Verbs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let any MCP-capable agent use the core verbs (code index, memory, ingestion, spec engine) through one governed boundary: registry + description pin, root confinement, operator-controlled policy/audit config, untrusted-tagged recall, full audit.

**Architecture:** `gateway/mcp_guard.py` provides `governed(name, spec_lookup)`, a decorator every MCP tool goes through: `guard_tool` (registry + pin) -> root confinement -> effective config (project config with security-sensitive keys forced from the operator's config) -> audit -> call -> errors returned as `{"error": ...}`, never raised. `gateway/mcp_server.py` registers thin tools; no business logic.

**Tech Stack:** Python 3.12, `mcp` SDK (FastMCP), Pydantic v2. Existing core verbs unchanged.

**Spec:** `docs/superpowers/plans/` is the only design record for this slice; it implements the follow-ups named in `docs/BACKLOG.md` ("MCP tool exposure gap", spec-engine v2 "MCP exposure", code-index "decide check_policy/audit before exposing"). Rulings are listed under Global Constraints.

## Global Constraints

- Gateway holds no business logic; each tool calls one core verb and shapes the result (`gateway/CLAUDE.md`).
- Rulings (made here, flagged for review): (1) `orchestrate_tasks` is **not** exposed — it takes Python callables, which cannot cross MCP. (2) Tools take string paths; every `root`/`cwd` is resolved and must lie inside `gateway.allowed_roots` (default: the gateway process's cwd); anything else is denied and audited as `mcp_root_denied`. (3) The **effective config** for a call is the target project's config with these keys forced from the operator's (gateway cwd) config: `audit`, `policy`, `paths.policies_dir`, `security`, `gateway`, `spec.enforce_command_policy`, `spec.allow_ungrounded`, `spec.allow_fileless_checks`, `spec.trivial_max_requirements` — a project (i.e. the agent) cannot loosen its own governance. (4) `query_memory` returns each fact's text wrapped by `tag_untrusted(source="memory")` plus `risk_flags`. (5) `tasks_feature` over MCP accepts interactive tasks only (no `run`). (6) Existing `verify_output` keeps resolving the target project's `verify.*` (needed for its own test command) — noted risk: that command is project-controlled; backlog.
- Every tool needs a `tool_registry.yaml` entry with `enabled: true` and a `description_sha256` pin; a test fails if a registered MCP tool lacks either, or a pin is stale (re-pin with `promptwise pin-tools`).
- TDD; Conventional Commits; no AI-attribution trailers; tests use `tmp_path` configs and never the repo's `.promptwise/`.
- Tool failures return `{"error": "<message>"}`; unexpected exceptions return `{"error": "internal error: <ExceptionType>"}` and are audited with `result="error"`.

## Review Focus

1. `root`/`cwd` with `..`, an absolute path elsewhere, or a symlink out of the allowed root -> denied + audited, verb never runs (Task 1, 2).
2. A project `.promptwise/config.yaml` that sets `spec.allow_ungrounded: true`, `paths.policies_dir`, or `audit.log_path` -> ignored via MCP (Task 1).
3. Recalled memory containing injection text -> returned wrapped in `<untrusted>` with `risk_flags` (Task 3).
4. Tool description edited without re-pinning -> every tool denied with a clear message (Task 2).
5. A verb raising `ValueError` (unknown spec, bad stage) -> `{"error": ...}`, not a transport error (Tasks 2-4).

---

### Task 1: `gateway/mcp_guard.py`

**Files:** Create `gateway/mcp_guard.py`, `gateway/tests/test_mcp_guard.py`.

**Interfaces:**
- Produces:
  - `allowed_roots(operator_config: dict) -> list[Path]` — `gateway.allowed_roots` (list of str) resolved, else `[Path.cwd().resolve()]`.
  - `confine(operator_config: dict, value: str) -> Path | None` — `""` -> first allowed root; else `Path(value).resolve()` (follows symlinks) must be inside an allowed root, else `None`.
  - `effective_config(operator_config: dict, root: Path) -> dict` — `resolve_config_auto(root=root)` then force the trusted keys from `operator_config` (Global Constraints ruling 3).
  - `governed(name: str, spec_lookup: Callable[[str], tuple[str, dict]], root_params: tuple[str, ...] = ("root",))` — decorator; the wrapped function receives `(config, root: Path, **kwargs)` with `root` the confined first root param (default allowed root when absent) and `config` the effective config; returns the tool's dict. Order: operator config (`resolve_config_auto()`) -> `guard_tool` (deny -> `{"error": reason}`) -> confine each name in `root_params` present in kwargs (deny -> audit `mcp_root_denied`, `{"error": "path outside allowed roots"}`) -> call -> audit `actor="mcp"`, `action=name`, `target=str(root)`, `result` allow/error; `ValueError` -> `{"error": str(exc)}`; other exceptions -> `{"error": "internal error: <Type>"}`.
- [ ] **Step 1: failing tests** — `test_confine_*` (empty -> default root; `..` escape -> None; absolute elsewhere -> None; inside -> Path; symlink out -> None, skipped if symlinks unsupported), `test_effective_config_forces_trusted_keys` (project config tries `spec.allow_ungrounded: true`, `paths.policies_dir`, `audit.log_path`; operator values win; non-trusted project keys such as `verify.test_command` survive), `test_governed_denies_unregistered_and_mismatched_pin`, `test_governed_denied_root_is_audited_and_verb_not_called`, `test_governed_returns_value_error_as_error_dict`, `test_governed_unexpected_exception_is_internal_error_and_audited`, `test_governed_audits_allowed_call`.
- [ ] **Step 2: run** `python -m pytest gateway/tests/test_mcp_guard.py -q` — FAIL (module missing).
- [ ] **Step 3: implement** per Interfaces; use `functools.wraps` so FastMCP sees the original signature/docstring.
- [ ] **Step 4: run** the same command — PASS.
- [ ] **Step 5: commit** `feat(gateway): governed MCP tool boundary (pin, root confinement, trusted config, audit)`.

### Task 2: Move `verify_output` onto the guard; code index + memory + ingestion tools

**Files:** Modify `gateway/mcp_server.py`, `tool_registry.yaml`, `core/config/defaults.yaml` (`gateway.allowed_roots: []`); Create `gateway/tests/test_mcp_tools_data.py`.

**Interfaces:**
- Consumes: Task 1; `query_code_index`, `record_memory`, `query_memory`, `run_ingestion_sweep`, `tag_untrusted`.
- Produces MCP tools (all via `governed`): `query_code_index(symbol: str, root: str = "", kind: str = "") -> {"locations": [CodeLocation dicts]}`; `record_memory(text: str, scope: str, root: str = "", session_id: str = "") -> {"facts": [...]}`; `query_memory(query: str, scope: str, root: str = "", session_id: str = "", allow_pii: bool = True, limit: int = 10) -> {"facts": [{id, text, category, pii, scope, risk_flags}]}` with `text` = `tag_untrusted(fact.text, "memory").wrapped`; `run_ingestion_sweep(root: str = "", session_texts: list[str] = [], session_id: str = "") -> IngestionResult dict`. `verify_output` keeps its signature and result; `cwd` is confined.
- [ ] **Step 1: failing tests** driving each tool through `mcp_app.call_tool` with a tmp operator config (registry file + pins written via `write_pins`): code index finds a symbol in a tmp repo; denied root; record then query memory round-trips with wrapped text and `risk_flags == ["instruction_override"]` for an injection-shaped fact; sweep returns an `IngestionResult` dict; Ollama/Qdrant down degrades without an error dict (reuse `http_post` failure behaviour); existing `verify_output` tests still pass unchanged.
- [ ] **Step 2: run** — FAIL.
- [ ] **Step 3: implement** the tools; update `tool_registry.yaml` with the four new entries and run `python -m scripts.promptwise pin-tools`.
- [ ] **Step 4: run** `python -m pytest gateway -q` — PASS.
- [ ] **Step 5: commit** `feat(gateway): expose code index, memory and ingestion verbs over MCP`.

### Task 3: Spec-engine tools + registry/pin consistency test

**Files:** Modify `gateway/mcp_server.py`, `tool_registry.yaml`; Create `gateway/tests/test_mcp_tools_spec.py`, `gateway/tests/test_mcp_registry_consistency.py`.

**Interfaces:**
- Produces MCP tools: `specify_feature(request: str, requirements: list[str], complexity: str = "standard", root: str = "")`; `plan_feature(spec_id: str, approach: str, root: str = "")`; `tasks_feature(spec_id: str, tasks: list[dict], checks: list[dict], root: str = "")` (task dict keys `id`, `requirement_ids`, `depends_on`, `expected_symbols`, `task_type`; check dict keys `requirement_id`, `command`, `files`; any `run` key is rejected with an error); `complete_task(spec_id: str, task_id: str, evidence: str, cwd: str = "", root: str = "")`; `verify_feature(spec_id: str, root: str = "")`; `converge_feature(spec_id: str, root: str = "")`; `amend_check(spec_id: str, requirement_id: str, command: str, files: list[str], reason: str, root: str = "")`. Each returns the verb's result `.model_dump()`.
- [ ] **Step 1: failing tests** — full lifecycle via `call_tool` in a tmp project (specify -> plan -> tasks -> complete_task denied by default policy `policy_denied:R1` -> operator policy allows `shell:run:python` -> accepted -> verify_feature verified -> converge not stale); project config cannot enable `spec.allow_ungrounded`; `run` key rejected; unknown spec -> `{"error": "unknown spec ..."}`; consistency test: every tool in `mcp_app.list_tools()` has an enabled registry entry whose pin equals `tool_description_hash(live_tool_spec(name))`, and every enabled registry entry is a live tool.
- [ ] **Step 2: run** — FAIL.
- [ ] **Step 3: implement**; re-run `pin-tools`.
- [ ] **Step 4: run** `python -m pytest gateway core/tests/spec -q` — PASS.
- [ ] **Step 5: commit** `feat(gateway): expose the spec engine over MCP`.

### Task 4: Docs, CLI visibility, status

**Files:** Modify `gateway/CLAUDE.md`, `docs/ARCHITECTURE.md` (MCP tool list), `docs/ROADMAP.md`, `docs/BACKLOG.md`, `CLAUDE.md`; Modify `scripts/promptwise.py` + `scripts/tests/test_cli.py` (`promptwise mcp tools` lists tool names with pin status).
- [ ] **Step 1: failing CLI test** — `runner.invoke(app, ["mcp", "tools"])` exit 0 and every live tool name present with `pinned` or `UNPINNED`.
- [ ] **Step 2: run** — FAIL.
- [ ] **Step 3: implement** the command; update docs (tool list, rulings, root confinement + trusted-config model, backlog items: project-controlled `verify.test_command` risk, `orchestrate_tasks` not exposable, OpenAI-compat proxy still open).
- [ ] **Step 4: run** the full suite `python -m pytest -q` — PASS.
- [ ] **Step 5: commit** `docs(gateway): MCP exposure model, tool list and status`.

## Self-Review

- Spec coverage: backlog "MCP tool exposure gap" -> Tasks 2-3; code-index "decide check_policy/audit before exposing" -> Task 1 (confinement + audit + operator policy); spec-engine v2 MCP follow-up -> Task 3; injection tagging at the MCP boundary (BACKLOG Phase 3.5) -> Task 2.
- Type consistency: `governed(name, spec_lookup, root_params)` and `effective_config(operator_config, root)` named identically in Tasks 1-3.
- Not covered, deliberately: OpenAI-compat proxy, MCP 2026-07-28 stateless protocol check, auth/identity, outbound MCP client.
