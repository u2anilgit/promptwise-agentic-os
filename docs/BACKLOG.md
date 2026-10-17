# Backlog

Tracks work that's been identified but deliberately deferred — findings from code review, follow-up items from a plan's final review, and known gaps against the spec/architecture docs. Not a duplicate of `docs/ROADMAP.md` (phase sequencing) — this is the finer-grained "known issues + quick wins" list that lives between phases.

Each entry: what, why it matters, where it came from, status.

## Open

### From research refresh (`docs/research/2026-08-31-findings-refresh.md`, 2026-08-31)

Market/pattern research + repo status audit ahead of Phase 5 sub-project 2 (spec engine).
Not yet brainstormed/planned — flagging here so it isn't lost.

- [ ] **No SQLAlchemy/Alembic code exists anywhere in `core/`** despite being locked tech
  stack (root `CLAUDE.md:31`) — will block the spec engine's persistence layer if not
  planned before Phase 5 sub-project 2 starts.
- [ ] **`orchestrate_tasks`'s `route_request` call sits outside its per-node `try`** (can
  abort the whole DAG on one bad call, `core/routing/router.py:54`) — fix before/alongside
  the spec engine, which wraps `orchestrate_tasks` directly.
- [ ] **Audit-chain-integrated memory decisions** — tie `core/memory/` recall/promotion
  into `core/audit/` so "why did the agent remember this" is itself an audited decision.
  No researched competitor does this; real differentiation, small scope, needs its own
  brainstorm.
- [x] **CHECKED 2026-10-16** (`docs/research/2026-10-16-mcp-2026-07-28-compat.md`): the server runs on `mcp 1.29.0`, which speaks protocol versions up to 2025-11-25 only; design is already stateless; migration to SDK 2.x tracked below. Original: **Confirm in-process MCP server targets the 2026-07-28 MCP spec revision** (stateless
  core, Multi Round-Trip Requests replacing server-initiated streaming) before Phase 6
  dashboard's WebSocket/live-feed design locks in assumptions the new spec removes.
- [ ] **`core/actions/` is undocumented** — exists on disk, not in `core/CLAUDE.md`'s
  target layout diagram. Check what it contains before spec-engine work starts; may
  already own relevant plumbing.

### From `orchestrate-tasks` plan (merged `9fe587d`, 2026-08-24)

Final whole-branch review found 0 blocker, 0 major, 3 minor — merged as-is per the reviewer's
explicit recommendation. See `docs/superpowers/plans/2026-08-24-orchestrate-tasks.md` and
`docs/superpowers/specs/2026-08-24-orchestrate-tasks-design.md`.

- [ ] **Duplicate node ids report as "dag contains a cycle" rather than a distinct error** —
  `core/orchestrate/graph.py`'s `topological_order`: two `DagNode`s sharing an `id` aren't
  explicitly checked; Kahn's algorithm degrades to reporting them as if the DAG were cyclic
  (fails closed either way — no node runs — so this is a diagnostics-quality issue, not a
  correctness one). Fix: add an explicit duplicate-id check ahead of the cycle detection, with a
  clearer error message.
- [ ] **`route_request` sits outside `orchestrate_tasks`'s per-node `try`** **(FIXED 2026-10-16: moved inside try, hw/catalog resolved once per call)** —
  `core/orchestrate/runner.py`: if `route_request` itself raises (`ValueError("no eligible tiers
  in catalog...")`, `core/routing/router.py:54` — reachable with a cloud-only catalog and a
  `privacy_sensitive=True` node mid-DAG), that exception propagates out of `orchestrate_tasks`
  entirely, aborting the whole call after earlier nodes' side effects have already run. This
  technically violates the plan's Global Constraint that only a structurally invalid DAG (cycle/
  dangling ref) should abort the whole call — everything else is supposed to degrade per-node.
  Narrow trigger condition under the default catalog, which is why the final review classified it
  minor rather than major, but real. Fix: move the `route_request` call inside the per-node `try`,
  or catch its `ValueError` specifically and degrade that one node to
  `routing_decision=None`/`status="error"` rather than letting it abort the DAG.
- [x] **`route_request` re-resolves hardware+catalog once per node, no caching across the loop** **(FIXED 2026-10-16: resolved once per call)**
  — a performance nit (`detect_hardware()` + `load_catalog()`'s YAML read happen on every node),
  not a correctness defect. Fix: resolve once per `orchestrate_tasks` call and thread through via
  `route_request`'s existing `hardware`/`catalog` parameters.
- [x] Post-plan follow-ups named in the plan/spec themselves: **sub-project 2 — the spec engine**
  (`specify/plan/tasks/implement/verify`, EARS artifacts) — needs its own brainstorm, will consume
  `orchestrate_tasks` directly; declarative DAG loading for pack-provided `dags/*.yaml` templates
  (`docs/ARCHITECTURE.md` §3); a parallel execution strategy if profiling on a real wide DAG ever
  shows sequential execution is a bottleneck; MCP tool exposure for `orchestrate_tasks`.

### From `ingestion-sweep` plan (merged `d83c846`, 2026-08-24)

Final whole-branch review was CLEAN — no findings, no fix wave. See
`docs/superpowers/plans/2026-08-24-ingestion-sweep.md` and
`docs/superpowers/specs/2026-08-24-ingestion-daemon-design.md`. The design spec's own deferred
scope (deliberately out of this sub-project, per its Rulings 1-2):

- [ ] **A reference ops recipe that actually calls `run_ingestion_sweep` on a cadence** — this
  sub-project ships the verb only; nothing in this repo invokes it yet. Add a documented cron
  entry / systemd timer / Windows Task Scheduler task / future gateway-hosted scheduler example.
- [ ] **Automatic session-transcript capture / watched-folder ingestion** — deliberately deferred
  (design spec Ruling 2) until a policy model exists for "what may be auto-ingested" (per-source
  policy, rate limiting, consent). `run_ingestion_sweep`'s `session_texts` parameter is ready to
  receive whatever that future capture mechanism produces; no rework needed on this side.
- [ ] **MCP tool exposure for `run_ingestion_sweep`**, mirroring the other two Phase 4
  sub-projects' eventual MCP wrappers.

### From `memory-fact-layer` plan (merged `3f56319`, 2026-08-24)

Final whole-branch review found 3 Major findings, all fixed before merge (`1f639e5`): unreachable
Qdrant crashed both `record_memory`/`query_memory` (unguarded `ensure_collection`, plus a leaked
SQLite connection on that path); `upsert_fact`/`vector_search` failures crashed instead of
degrading to BM25-only as the module's own docstring claimed; `embed_text`'s except clause missed
`json.JSONDecodeError` and didn't guard a non-dict response body. See
`docs/superpowers/plans/2026-08-24-memory-fact-layer.md` and
`docs/superpowers/specs/2026-08-24-memory-fact-layer-design.md`. These are the rest, deliberately
deferred:

- [ ] **`scope="session"` is not filtered by `session_id` in `query_memory`** **(FIXED 2026-10-16: session_id threaded through SQLite, Qdrant payload and fallback)** (Major, deferred not
  fixed) — `record_memory` accepts and persists `session_id`, but `query_memory` has no
  `session_id` parameter, and neither `search_fts` nor `vectors.search`/`upsert_fact`'s Qdrant
  payload carry it. A session-scoped query today returns facts from every session, not just the
  caller's. Both verb docstrings in `core/memory/memory.py` now disclose this explicitly. Fix:
  add `session_id: str | None = None` to `query_memory`, thread it into `search_fts` as a new
  optional predicate, add it to `vectors.search`'s filter and `upsert_fact`'s payload. Sub-project
  3 (ingestion daemon) is the first planned real consumer of session scope — do this before or
  alongside that work, not speculatively now.
- [x] **Duplicated row→`Fact` hydration** **(FIXED 2026-10-16: _row_to_fact + get_fact in store.py)** — the same 8-column positional row shape is unpacked
  into a `Fact` in both `core/memory/store.py` (`search_fts`) and `core/memory/memory.py`
  (`query_memory`'s vector-only-fallback SELECT). A `_SCHEMA` column reorder would silently
  corrupt one of them without a compiler/type error. Fix: add `_row_to_fact(row) -> Fact` and a
  `get_fact(conn, fact_id) -> Fact | None` to `store.py`; have `memory.py` call `get_fact` instead
  of hand-rolling the SELECT.
- [x] **`query_memory`'s SQLite fallback SELECT has no scope/root predicate** **(FIXED 2026-10-16: get_fact enforces scope/root/session)** — `SELECT ... FROM
  facts WHERE id = ?` trusts the id list from vector search entirely; safe today only because
  `vectors.search` already filters by scope+root, but it's the one place a fact could enter the
  result set without its own scope check. Defense in depth: add `AND scope = ?` (and the root
  predicate when set) to the fallback query.
- [x] **`query_memory` isn't audited on the normal (no-PII-exclusion) path** **(FIXED 2026-10-16: now audited on every call)** — `record_audit`
  only fires inside `if excluded_count:`, so an ordinary query leaves no audit trail at all,
  against goal 4's "every fs/shell/DB/cloud action is governed and audited." Plan-inherited (the
  plan's own sample code did this), not implementer drift. Fix: call `record_audit`
  unconditionally once per `query_memory` call, with `detail={"result_count": ..., "pii_excluded_count": ...}`.
- [x] **PII flag is whole-input, not per-fact** — `contains_pii(text)` runs once on the raw input
  and stamps every fact extracted from it, so one email address in a long transcript flags every
  sibling fact. Conservative (over-flags, never under-flags), not a leak, but degrades
  `allow_pii=False` recall over time. Fix (later): flag per extracted fact instead, or document
  the whole-input choice as intentional.
- [ ] **Session-scope config resolution falls back to process cwd** — `record_memory`/
  `query_memory` call `resolve_config_auto(root=Path(root) if root else None)`; for legitimate
  session-scope calls `root` is `None`, so config/db-path resolution falls back to process cwd —
  the same bug *class* Phase 2 already fixed once (MCP caller cwd ≠ target project cwd). Only
  reachable when a caller omits `config`, which no current test does. Decide and document where
  session-scoped memory should actually live (a user-level path, not cwd) before a real caller
  hits this.
- [ ] **`route_request` call in `extract_facts` sits outside its own `try` block** **(FIXED 2026-10-16: moved inside try)** — latent, not
  observed: `route_request` can raise `ValueError("no eligible tiers in catalog...")`
  (`core/routing/router.py:54`), and the call is one line above `extract_facts`'s `try:`, so that
  specific exception would escape the "never raises" contract. Four attempted degenerate configs
  (empty tier order, cloud-only under local_only, missing catalog, nonexistent tier) all had the
  router's own fallback absorb them instead — reviewer could not trigger it live. Fix: move the
  `route_request` call inside the existing `try` (the `except Exception` already returns the
  correct unclassified-fact fallback).
- [x] Post-plan follow-ups named in the plan itself: MCP tool exposure for `record_memory`/
  `query_memory` (mirrors `verify_output`'s and the code index's eventual MCP wrapper);
  `kind="doc_chunk"` extension for general RAG (deliberately out of this sub-project's scope);
  `services.ollama`/`services.qdrant` real health checks in `core/diagnostics/checks.py`
  (currently `_not_yet_implemented` stubs) — `promptwise doctor` should report whether this
  sub-project's runtime dependencies are actually reachable.

### From `pack-loader-foundation` plan (merged `aa9cf4a`, 2026-08-24)

Final whole-branch review findings not fixed before merge (see `docs/superpowers/plans/2026-08-24-pack-loader-foundation.md` and the design spec it implements, `docs/superpowers/specs/2026-08-24-repo-intelligence-methodology-packs-design.md`).

- [x] **Symlink handling unconsidered** — fixed 2026-08-24. `list_installed_packs` now excludes symlinked entries (`is_dir() and not is_symlink()`) instead of counting them as installed packs; `remove_pack` now `unlink()`s a symlinked `packs/installed/<name>` instead of calling `shutil.rmtree` through it (which either raises or, worse, would delete whatever the link points at). Regression tests added, gated behind a symlink-capability probe (same skipif convention as the semgrep/gitleaks tests) since this dev environment lacks the Windows privilege to create symlinks — untested by CI/this session, verify on a symlink-capable machine before relying on it in production.
- [x] **`dependencies` parsed but never resolved** — fixed 2026-08-24, now that Phase 3 is done. `install_pack` refuses to install a pack whose declared `dependencies` aren't already present in `packs/installed/`. Deliberately scoped down to presence-checking only, not full resolution — see the still-open item below.
- [ ] **`check_policy` capability registration not built** — an installed pack's declared `capabilities` (e.g. `shell:run:ruff`) aren't automatically registered as policy grants; check_policy has no actor/pack-scoped concept yet, only a flat action-string match. Needs a real design pass (how does a pack-declared capability become a policy rule scoped to *that pack's* actions, without silently widening what every other actor can do?) before implementation — don't build ad hoc.
- [ ] **Dependency resolution is presence-only, not version-constrained or auto-installing** — `install_pack` checks a dependency exists in `packs/installed/`, not that its installed version satisfies any range, and never installs a missing dependency automatically (the operator must `pack install` it first, in order). Fine for the current small pack count; revisit if/when Phase 8's pack catalog grows enough that manual dependency ordering becomes annoying.

### From `code-index` plan (merged `deab912`, 2026-08-24)

Final whole-branch review findings not fixed before merge — 1 major + 1 minor (file-level I/O
guard, non-directory `root`) were fixed before merge (`12d3288`); these are the rest, deliberately
deferred (see `docs/superpowers/plans/2026-08-24-code-index.md` and
`docs/superpowers/specs/2026-08-24-code-index-design.md`).

- [ ] **`LIKE` pattern doesn't escape `_`/`%`** — `core/index/store.py`'s `query_symbol` builds
  `WHERE symbol LIKE '%{symbol}%'` without escaping; `_` (matches any one char) is common in
  Python symbol names, so e.g. `foo_bar` also matches `fooXbar`. Not a SQL-injection risk
  (parameters are bound), just an over-match. Fix: escape `\`, `%`, `_` in the pattern and add
  `ESCAPE '\'` to the clause.
- [ ] **No concurrency/lifecycle test coverage** — the fix for "connection never closed" and
  "no WAL/timeout" (both from the per-task review) shipped without a regression test; both are
  one-line assertions if picked up.
- [ ] **Nested local function inside a method misclassified `kind="method"`** — Python's
  `_is_inside_class` walks all ancestors, so a plain function nested inside a method is labelled
  a method too. Low impact (file/line is still correct, only the `kind` filter is affected).
  Fix: stop the ancestor walk at the first enclosing `function_definition`.
- [ ] **`index.db_path` not declared in `core/config/defaults.yaml`** — works via its hardcoded
  fallback, but is undiscoverable next to the rest of `core/`'s declared config keys.
- [ ] **Code index DB (+ WAL/shm files) not gitignored** — `.promptwise/code_index.sqlite3*` will
  dirty `git status` once this verb runs against this repo or is exposed over MCP. Same
  pre-existing gap as `.promptwise/audit.jsonl`, but this branch is the first to write a binary,
  always-regenerable artifact there.
- [ ] **Stale-row sweep isn't scoped to `root`** — `query_code_index` never normalizes `root`
  (no `.resolve()`), so a relative vs. absolute `root` for the same repo produces disjoint file
  keys and the incremental-reindex sweep silently degrades to a full reparse; a shared DB across
  two roots would delete each other's rows. Correctness holds (results always rebuild), only the
  incremental-reindex guarantee is at risk. Fix: normalize `root` and/or scope the sweep query.
- [ ] **No `check_policy`/`record_audit` on the verb's fs/DB access** — against goal 4's "every
  fs/shell/DB/cloud action is governed and audited", but the spec/plan are silent on it and
  existing precedent is mixed (`fs.py` gates writes, `verify_output` doesn't gate its shell-outs).
  Decide explicitly before the follow-up task that exposes `query_code_index` over MCP — that's
  the point an untrusted agent, not core itself, picks `root`.
- [ ] **Plan's own post-plan follow-ups** — MCP tool exposure for `query_code_index` (mirrors
  `verify_output`'s wrapper in `gateway/mcp_server.py`); reference-finding ("what calls Y") as a
  natural extension of the same store, needs its own query captures + spec section.
- [ ] Symlink-cycle regression test (`test_query_code_index_does_not_follow_a_symlinked_
  directory_cycle`) is skipped on this dev machine (no Windows symlink privilege) — confirm it
  actually runs and passes on a Linux/symlink-capable box before relying on the guard in prod.

### Architecture-advisor pack (idea, not started)

Research done 2026-08-24: `docs/research/architecture-patterns-cloud-reference.md` — software architecture pattern decision table (layered, microservices, event-driven, CQRS, DDD, hexagonal, SOA, etc.), cloud service/deployment model reference, AWS/Azure/GCP 2026 comparison, and a 4-question recommendation heuristic. Proposed shape: `packs/registry/architecture-advisor/` (kind: `intelligence`) that takes project context and returns a ranked pattern + cloud recommendation with rationale. Depends on nothing blocking implementation directly, but best sequenced after Phase 5 (spec engine) if it wants structured project-context intake rather than ad hoc prompting.

### Repo-intelligence / methodology packs (blocked, tracked here so it isn't lost)

From `docs/superpowers/specs/2026-08-24-repo-intelligence-methodology-packs-design.md` — content blocked on Phases 3 (`check_policy`/`record_audit`), 4 (code index), 5 (spec engine/`orchestrate_tasks`), none of which exist in code yet.

- [ ] `repo-intelligence` pack (kind: intelligence) — feature/requirements/architecture/pseudocode/design extraction DAG.
- [ ] `bmad-methodology` pack (kind: lifecycle) — Business-model→Architecture→Design→Development DAG.
- [ ] `dmaic-methodology` pack (kind: lifecycle) — Define-Measure-Analyze-Improve-Control DAG.
- [ ] Open questions for whichever plan picks these up: complexity-threshold default for pseudocode extraction (config-tunable?); whether `extract-requirements`' EARS inference reuses Phase 5's spec-engine logic as a shared helper or reimplements it; golden-fixture repo size for the test suite.

### Phase-level (from `docs/ROADMAP.md`)

- [x] **Phase 2 (Verification Gate)** — confirmed 2026-08-24: all four `core/verify/` acceptance criteria have real, passing tests (`core/tests/verify/`), including a genuine end-to-end MCP `call_tool` test (previously only tool-registration was checked). Found and fixed a real bug along the way: `verify_output` resolved org/project config from the *process* cwd instead of the `cwd` argument — broke any MCP caller whose target project differs from the gateway's own working directory. Fixed in `d3978e6`.
- [x] **Phase 3 (Governed system control)** — found already implemented on unmerged branch `worktree-phase3-governed-system-control` (5 commits: check_policy engine, hash-chained audit log, JIT grants, governed fs_write, MCP tool allowlist, support-bundle generator), not previously recorded in session status. Rebased onto master, code-reviewed, 3 real bugs found and fixed before merge (`f2f48fa`): `fs_write` scoped policy by filename only (directory-scoped allow/deny was unexpressible), `undo_buffer_max: 0` didn't disable undo history (Python `[-0:]` slice quirk), audit log's `_last_hash` rescanned the whole file on every write (O(n²) over a session) — fixed with a chunked tail-seek, which surfaced a Windows CRLF line-ending bug fixed alongside it. Merged to master `7b427a2` 2026-08-24, full suite green (198 passed, 1 skipped, pushed to origin).
  - **Deferred, not a blocker:** `record_audit` called inline at 2 call sites within `fs_write` rather than via a shared decorator/middleware (`core/CLAUDE.md`'s stated convention) — acceptable with only one governed verb so far; revisit when the second governed action (e.g. `shell_exec`) is added, so the wrapper pattern is designed against two real call sites, not speculatively.
  - **Deferred, not a blocker:** JIT grants, fs_write, tool_registry, and audit log are all unauthenticated, single-process, cooperative-locking-free JSON/JSONL stores — fine for Phase 0-6's zero-cost single-node target, will need real locking or a DB-backed store if/when multi-process concurrency is introduced.
- [x] **Phase 4 sub-project 1 of 3 (code index)** — `core/index/`: tree-sitter Python/TS/TSX/JS
  definition extraction (`parser.py`), SQLite symbol store with mtime invalidation (`store.py`),
  and the public `query_code_index` verb (`query.py`) tying walk+reindex+query together.
  Individually task-reviewed (Tasks 1-3 clean; Task 4 had 1 major + 4 minor, fixed `da6ce86`),
  then finally whole-branch-reviewed (1 more major + 8 minor found; the major — file-level I/O
  errors crashing the whole query — and a related minor fixed `12d3288`, rest logged above).
  Merged to master `deab912` 2026-08-24, full suite green (226 passed, 4 skipped).
- [x] **Phase 4 sub-project 2 of 3 (memory/fact layer)** — `core/memory/`: `Fact` model,
  SQLite+FTS5 fact store (`store.py`), PII detector extending `redact.py` (`contains_pii`),
  Ollama embeddings (`embed.py`), local-model fact extraction via `route_request` (`extract.py`),
  Qdrant vector wrapper (`vectors.py`), Reciprocal Rank Fusion (`rank.py`), and the public
  `record_memory`/`query_memory` verbs (`memory.py`) tying hybrid BM25+vector retrieval together.
  8 tasks, individually task-reviewed (Task 2 had a real FTS5-keyword-crash bug, 1 fix round;
  Task 8 caught+fixed a plan defect — `AuditRecord.result` doesn't accept "success"), then finally
  whole-branch-reviewed (3 more major cross-task findings + 9 minor; the majors — unguarded Qdrant
  calls crashing both verbs, `embed_text` missing `JSONDecodeError` — fixed in one wave `1f639e5`,
  rest logged above). Merged to master `3f56319` 2026-08-24, full suite green (266 passed,
  4 skipped).
- [x] **Phase 4 sub-project 3 of 3 (ingestion sweep)** — `core/ingestion/`: `IngestionResult`
  model and the one public verb, `run_ingestion_sweep`, composing the already-merged code index
  (`query_code_index`) and memory layer (`record_memory`) — refreshes the code index and records
  caller-supplied session text as facts. Deliberately ships as a single idempotent verb an
  external scheduler invokes, not a persistent background process/watcher/daemon (design spec
  Ruling 1 — the lower-risk shape per explicit "safer, full autonomous mode" instruction). 2
  tasks, both individually reviewed clean with zero fix rounds, then finally whole-branch-reviewed
  CLEAN (0 findings) — including a grep-verified scope-boundary audit confirming no
  thread/asyncio/subprocess/watchdog/scheduling code exists anywhere in the module. Merged to
  master `d83c846` 2026-08-24, full suite green (274 passed, 4 skipped).
  **Phase 4 (Memory & code context) is now fully complete — all 3 sub-projects merged.**
- [x] **Phase 5 sub-project 1 of 2 (`orchestrate_tasks` DAG runner)** — `core/orchestrate/`:
  `DagNode`/`Dag`/`NodeResult`/`DagResult` models, `topological_order` (Kahn's algorithm, cycle/
  dangling-ref detection), and the public `orchestrate_tasks` verb — topological execution of
  caller-supplied node callables with per-node `route_request` tier hints, fail-soft dependent-
  skip on a node failure, and per-node audit. Deliberately sequential (no threads) and never
  invokes an LLM/agent itself — pure orchestration bookkeeping over whatever the caller's
  callables do (design spec Rulings 1-2). 3 tasks, all individually reviewed clean with zero fix
  rounds, then finally whole-branch-reviewed with 0 blocker/0 major/3 minor — merged as-is per the
  reviewer's explicit recommendation (minors logged above). Merged to master `9fe587d`
  2026-08-24, full suite green (292 passed, 4 skipped).
- [ ] **Phase 5 sub-project 2 of 2 (spec engine)** — `specify/plan/tasks/implement/verify`,
  EARS-format acceptance-criteria artifacts, wrapping sub-project 1's `orchestrate_tasks`. Not
  started — needs its own brainstorm now that its dependency exists.

### From full-codebase audit, 2026-09-08

Deep pass across `docs/ROADMAP.md`, `docs/BACKLOG.md` (prior entries), and the actual tree
(`core/`, `gateway/`, `dashboard/`, test collection) to confirm implemented-vs-missing state and
re-surface priority. Confirmed: 296 tests collected (292 pass, 4 skip — gitleaks binary absent,
symlink tests need a symlink-capable machine), matching `CLAUDE.md`'s status line. No new bugs
found beyond what was already logged above; this batch is scope/priority findings, not defects.

- [ ] **`dashboard/` has zero code** — only `dashboard/CLAUDE.md` exists, confirming Phase 6 has
  not started. First user-visible surface of the whole project; still fully blocked on Phase 5.
- [ ] **`core/actions/` remains undocumented** in `core/CLAUDE.md`'s target layout diagram —
  contains `fs.py`/`models.py` (governed `fs_write` lives here per the Phase 3 entry above) but
  was never added to the doc. Audit and document its actual contents/ownership before spec-engine
  work builds anything adjacent to it (carried forward from the research-refresh entry above,
  re-confirmed still open).
- [ ] **No SQLAlchemy/Alembic code exists anywhere in `core/`** despite being locked stack
  (root `CLAUDE.md:31`) — re-confirmed still true by directory scan. This is the single highest-
  risk gap for Phase 5 sub-project 2: the spec engine needs a persistence layer and no decision
  or scaffold exists yet. Decide the schema/migration approach *before* sub-project 2 starts, not
  mid-implementation.
- [x] **FIXED 2026-10-16 (branch feat/mcp-exposure; `docs/superpowers/plans/2026-10-16-mcp-exposure.md`)** — 12 tools now exposed through `gateway/mcp_guard.py`; `orchestrate_tasks` deliberately not (takes callables). Original: **MCP tool exposure gap** — only `verify_output` and the code-index verb are wired into the
  MCP server (`gateway/mcp_server.py`); `record_memory`, `query_memory`, `run_ingestion_sweep`,
  and `orchestrate_tasks` are all callable as core verbs but not yet exposed as MCP tools, despite
  each sub-project's own plan naming this as a named follow-up. Batch these into one MCP-wiring
  pass rather than one-off per verb — same registration/allowlist pattern each time.
- [ ] **Priority re-statement for planning purposes** (no code change, ordering only): (1) fix the
  two logged `route_request`-outside-`try` bugs (`orchestrate_tasks` + `extract_facts`) and the
  `query_memory` session-scope leak — cheap, and the spec engine inherits both classes of bug by
  wrapping `orchestrate_tasks` directly; (2) settle the SQLAlchemy/Alembic persistence decision
  above; (3) Phase 5 sub-project 2 (spec engine) itself; (4) Phase 6 dashboard; (5) Phase 8 pack
  content, now that Phases 4-5's dependencies are solid.

### From status check, 2026-10-16

Full suite run: **289 passed, 4 skipped, 3 FAILED** — status line elsewhere (292/4) is stale.

- [x] **FIXED 2026-10-16** (default core audit log is now `.promptwise/agentic_audit.jsonl`; regression tests added; runtime state gitignored; suite 294 passed/4 skipped). Gap analysis: `docs/research/2026-10-16-agent-landscape-gap-analysis.md`. Original finding: **P0 — `audit.chain` doctor check FAILs on this dev repo** (`core/tests/diagnostics/test_checks.py::test_audit_chain_check_passes_by_default`, `::test_no_failures_means_clean_exit`, `scripts/tests/test_cli.py::test_doctor_exits_zero_when_no_failures`). Cause: the PromptWise *Claude Code plugin* hooks write their own-schema records (`agent`, `rules_applied`, `posttooluse_audit`…) into the same `.promptwise/audit.jsonl` Agentic OS uses; `verify_chain` fails at index 0. Real namespace collision, not tampering. Fix options: separate audit path for the core (e.g. `.promptwise/core/audit.jsonl`), and make tests use a tmp path rather than the process cwd. Also add `.promptwise/` to `.gitignore` (currently untracked noise).
- [ ] Untracked `docs/IMPLEMENTATION_ANALYSIS.md` (2026-09-04, findings F-01..F-16, target architecture) and `docs/ADOPTION_AND_CAPABILITY_RESEARCH.md` (adoption planes, capability matrix) — review, then commit as the new shared reference docs; fold accepted items into ROADMAP. New items they raise beyond this file: no CI workflow, OpenAI-compat endpoint unbuilt, no identity/tenancy/secrets/approval layer, no OTel emission, no durable job queue.
- [x] Persistence decision made 2026-10-16: SQLAlchemy 2 + Alembic for new code (`core/db/`), existing stores migrate opportunistically — see spec-engine v2 design Ruling 5.
- [ ] **`verify_output` vacuous pass**: empty `verify.test_command` yields `ran=False, passed=True`; v2 plan Task 0 adds `VerifyResult.grounded`. Also `run_command` shells out without `check_policy` (goal 4) — revisit when the governed `shell_exec` verb exists.
- [ ] Spec engine design + plan exist (`specs/2026-08-31-spec-engine-design.md`, `plans/2026-08-31-spec-engine.md`) but are not executed; blocked on the persistence decision above.

### From Phase 3.5 build, 2026-10-16

- [x] **DONE 2026-10-16 (branch feat/lockfile-and-llm-posture):** hash-pinned `requirements.lock` + `requirements-dev.lock` committed and validated (full suite 469 passed on Python 3.12.8 installed strictly from the dev lock); LiteLLM posture decided (not a dependency; see ARCHITECTURE.md). Original: **Generate and commit a real hash-pinned `requirements.lock`** (`uv pip compile --generate-hashes`; `uv` not installed in dev env) and decide LiteLLM posture — it is named in the locked stack but is not yet a dependency; when added, pin exact version and consider a sandboxed sidecar behind a thin provider interface. `doctor` currently WARNs `deps.integrity` (no lockfile).
- [ ] **Persist memory provenance/trust tier** — `tag_untrusted`/`scan_for_injection` exist and `record_memory` audits flags, but facts carry no stored trust tier, source or TTL (needs a store migration — blocked on the SQLAlchemy/Alembic decision). Also wrap recalled facts with `tag_untrusted` at the MCP boundary once `query_memory` is exposed.
- [ ] **Apply `tag_untrusted` to outbound MCP client results** when an outbound MCP client exists; same for `guard_tool` pinning of third-party servers.
- [ ] `live_tool_spec` reads FastMCP's private `_tool_manager`; a test pins it to `list_tools()`, but replace with a public accessor if the SDK adds one.

### From spec-engine v2 build, 2026-10-16

- [x] (done on feat/mcp-exposure; `promptwise spec` CLI still open) MCP exposure for the six spec verbs (`specify_feature`, `plan_feature`, `tasks_feature`, `complete_task`, `verify_feature`, `converge_feature`) plus `amend_check`; `promptwise spec` CLI.
- [ ] `amend_check` is audit-only; add a JIT grant requirement (`core/policy/jit.py`) so an agent cannot amend its own checks unattended.
- [ ] One frozen check per requirement (ruling); revisit if requirements routinely need independent commands.
- [ ] Acceptance-check commands run via `run_command` without `check_policy` (same gap as `verify_output`) — route through a governed `shell_exec` verb when it exists.
- [ ] Migrate `core/memory`, `core/index` and JSON stores onto `core/db` opportunistically (memory first, when provenance/trust tier columns are needed).
- [ ] Review minors (spec-engine v2): check `files` outside `root` accepted (M2); `complete_task` commits `done` before auditing and `tasks_feature` commits stage before orchestrating (M3); already-done shortcut unaudited and skips hash re-check (M4); `complete_task`/`verify_feature` audits lack `artifact_sha256` and the tasks hash omits `depends_on`/`requirement_ids` (M5); `converge_feature` unaudited (M6); full Alembic upgrade + new engine on every verb call (M7).
- [ ] Windows backslash paths in check commands fail closed (POSIX `shlex`); use forward slashes (review I3, deliberately not changed — would alter `verify.test_command` quoting).
- [ ] `verify_output` runs semgrep/gitleaks on every `complete_task` (≈5s each) — consider a cheaper per-task profile.

### From MCP exposure build, 2026-10-16

- [x] FIXED 2026-10-16 (security review of feat/mcp-exposure): MCP calls now run on operator config; project `verify.test_command`/`lint_command` honoured only if listed in `gateway.allowed_verify_commands`; governance state pinned to the gateway dir; pre-call audit fail-closed. Remaining: a governed `shell_exec` verb would let policy, not an exact-string allowlist, gate these commands.
- [ ] Operator files (`policies/`, `tool_registry.yaml`, audit log) default to repo-relative paths an agent can write; hardened deployments must relocate them via `PROMPTWISE_OPERATOR_CONFIG` (documented in `gateway/CLAUDE.md`). Consider a doctor check that WARNs when they sit inside an allowed root.
- [ ] MCP surface has no authentication (stdio trust model); `gateway.allowed_roots` is the only caller-independent control. Identity/tenancy is a separate project. The HTTP surface is now bearer-protected (dashboard slice 6a, single shared operator credential, no per-user attribution).
- [ ] Dashboard 6b follow-ups: no Playwright smoke test yet (component tests plus a manual real-browser pass only; add when a CI browser is available); the Dockerfile Node build stage and `.dockerignore` change are unverified (Docker daemon unavailable); `npm audit` reports advisories in dev-only tooling (vite/esbuild dev server, vitest) and none in runtime dependencies — upgrade the Vite/Vitest majors when convenient; `/api/v1/diagnostics` has an untyped response (`list[dict]`), so the UI types it by hand — give it a Pydantic model so it lands in the OpenAPI contract; routing is a tab switch, add a router with 6c.
- [ ] Dashboard 6a follow-ups: `/api/v1/audit` runs `verify_chain` over the whole file on every call (O(n); cache by file size+mtime once logs get large); `/api/v1/specs*` runs `migrate_to_head` (idempotent schema creation on a GET); `/docs` and `/openapi.json` are unauthenticated (schema only); `audit_events` polls the file (switch to an in-process notifier if latency matters).
- [x] DONE 2026-10-16 (branch feat/spec-cli): `promptwise spec specify|plan|tasks|complete|verify|converge|status|amend` (exit 0 ok / 1 rejected-or-stale / 2 error) plus read-only `spec_status` verb. Note: `spec_status`/`converge_feature` are unaudited reads.
- [x] DONE 2026-10-16 (branch feat/mcp-sdk2; see the compat note's Outcome section). Still open: Tasks extension for long `complete_task` runs, `_meta` OpenTelemetry propagation, replacing the private `_tool_manager` reads, `cache_hints` for `tools/list`. Original plan: **migrate `gateway/mcp_server.py` to SDK 2.x** (`FastMCP` -> `MCPServer` from `mcp.server.mcpserver`, `inputSchema` -> `input_schema`, verify `call_tool` result shape and stdio launch with a real client, public accessor instead of `_tool_manager`), then consider the Tasks extension for long `complete_task` runs and `_meta` OpenTelemetry propagation. Bound stays `mcp>=1.27,<2` until then.

- [ ] Review minors deferred (mcp-exposure): `record_memory`/`converge_feature`/error strings are not `<untrusted>`-wrapped; per-call resolve of `Path.resolve()` TOCTOU on subdirectories after confinement; `os.walk` in the code index may follow junctions out of the root; `semgrep_config` accepted from operator only now but remote rule URLs are not validated; symlink-escape test is skipped without privilege (a junction-based test would give real coverage on Windows); `gateway.allowed_roots` empty means gateway cwd only — multi-root deployments need explicit entries.

### From lockfile work, 2026-10-16

- [ ] `compose/gateway.Dockerfile` now installs from the lock and copies `policies/`, `security/`, `tool_registry.yaml` — verified only by simulating its steps (hash-verified `pip install` + app import); the Docker daemon was not running, so an actual `docker compose build` + `up` check is still owed.
- [ ] `.github/workflows/ci.yml` is unverified (cannot run GitHub Actions locally) and uses version tags (`actions/checkout@v4`, `actions/setup-python@v5`); pin actions by commit SHA as part of the supply-chain posture.
- [ ] `pyproject.toml` lower bounds (e.g. `fastapi>=0.115`) are older than anything tested (lock resolves `fastapi 0.143.3`, `starlette 1.8.0`); raise floors to the tested versions or add a floor-version CI job.
- [ ] Locked/tested set diverges from the earlier dev environment (`fastapi 0.115.12`); the suite passes on both, but only the lock set is the supported one.
- [ ] Re-lock cadence: schedule a periodic `--upgrade` + full-suite validation and an advisory check against `security/known_bad_packages.yaml`.

### From independent-verification build, 2026-10-17

- [ ] Ship a reference reviewer wrapper (a script that calls a chosen second model) and a reference mutation-tool wrapper as documented examples under `docs/` or a pack; core deliberately bundles neither.
- [ ] `expect_baseline='pass'` guards are an author-chosen escape hatch: consider requiring operator approval (or a distinct audit flag in the dashboard) for guards on specs that touch new behaviour.
- [x] FIXED (adversarial review): baselines run twice and must agree, reject tree-writing checks, distinguish missing program/timeout from a real failure, forbid-able guards, reviewer cwd/payload hardening, bounded reviewer output.
- [ ] Residual: a red check can still keep arming state outside the project tree; the tree-watch skips trees over 50k files (silently weaker) and ignores cache dirs; consider running baselines in a throwaway copy of the tree.
- [ ] Reviewer verdicts are not signed or bound to the verdict's own evidence hash (the payload carries `evidence_sha256`, but the reviewer need not echo it); no tree digest is sent. Mutation and reviewer commands are not routed through `check_policy` (operator-defined) and the reviewer inherits the gateway's full environment by design (it may need model API keys).
- [ ] Most legacy tests use `expect_baseline='pass'` fixtures (explicit guards); the default red-first path has dedicated tests but consider converting more fixtures.

## Resolved

- [x] Pack-loader foundation itself (schema/loader/registry/CLI/doctor wiring, `intelligence` pack kind) — `docs/superpowers/plans/2026-08-24-pack-loader-foundation.md`, merged `aa9cf4a` 2026-08-24.
- [x] `_registry_dir()` bypassed config resolution — now resolves `paths.packs_registry` via `resolve_path`, same as `_installed_dir()`.
- [x] `version` field unvalidated — `PackManifest` now validates it via `parse_version`.
- [x] Stale/wrong import-cycle comment in `core/diagnostics/checks.py` — corrected.
- [x] Duplicate zero-packs doctor test — removed.
- [x] Unused `_config(root)` test parameter — dropped, call sites updated.
- [x] Near-tautological `test_defaults_to_running_core_version` — now patches to a distinctive version.
- [x] Untested reinstall-over-existing branch — covered.
- [x] Reinstall non-atomic — `install_pack` now copies to a temp dir and swaps into place; a failed reinstall no longer deletes the existing install first.

All merged via `chore/pack-loader-cleanup`, 2026-08-24.
