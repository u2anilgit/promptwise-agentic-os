# Design: `orchestrate_tasks` — DAG Runner (Phase 5 sub-project 1 of 2)

Written autonomously per standing user instruction this session ("keep going ... full autonomous
mode ... safer"). Decisions below are rulings, not interactive Q&A, each recorded with its
cost-if-wrong, same convention as this session's prior two sub-projects' ledgers.

## Phase 5 decomposition (ruling 0)

`docs/ROADMAP.md`'s Phase 5 acceptance criterion — *"`specify → plan → tasks → implement → verify`
runs end-to-end on one real feature request, produces EARS-format artifacts, and the `implement`
step's output must pass Phase 2's gate before `verify` marks it done"* — names a pipeline, but
`docs/ARCHITECTURE.md` §2 is explicit that the spec engine **wraps `orchestrate_tasks`**, and
`orchestrate_tasks` does not exist anywhere in this repo yet (verified: zero references in
`core/`/`gateway/`). Building the spec-engine pipeline without its own foundation first would mean
either blocking mid-plan to design a dependency, or building both in one oversized plan — the
exact failure mode `superpowers:writing-plans`' Scope Check and `superpowers:brainstorming`'s
decomposition guidance both warn against.

**Decision:** split Phase 5 into two sub-projects, same pattern as Phase 4:
1. **`orchestrate_tasks`** (this spec) — the DAG runner core verb itself, standalone and useful
   independent of the spec engine (packs already plan to use it directly, per `ARCHITECTURE.md`
   §3's `dags/` pack contract entry).
2. **Spec engine** (`specify/plan/tasks/implement/verify` + EARS artifacts) — a later spec, wraps
   sub-project 1's verb. Not started, not designed yet — this document's job is only sub-project 1.

**Cost if wrong:** none structurally; this is the same sequencing Phase 4 already used
successfully (code index shipped before the memory layer that needed one of its design choices).

## Problem (sub-project 1 only)

`docs/ARCHITECTURE.md`'s Core Engine verb table: *"`orchestrate_tasks(dag)` — run a DAG of steps
across agents/tools, per-node tier | backs both spec-engine pipelines and pack-provided DAG
templates."* Nothing in `core/` runs a multi-step DAG today; every existing verb is a single
synchronous call.

## Ruling 1 (execution model — the "safer" bias): sequential, no concurrency

**Decision:** nodes execute one at a time, in topological order (Kahn's algorithm — same
approach `docs/research/v3-implementation-plan.md` never actually specifies an implementation
for, so this is this plan's own choice, not inherited). No `threading`/`asyncio`/`multiprocessing`.

**Why:** this session's ingestion-sweep sub-project already ruled out background
processes/threads for the same reason — concurrency is a real complexity and bug-surface increase
(shared-state races, partial-failure semantics across parallel branches, harder-to-reproduce test
failures) that nothing in this DAG runner's actual requirement demands yet. `route_request`
already tolerates being called synchronously many times (it's a pure function, no I/O beyond
config/catalog reads already cached by callers). A DAG with genuinely expensive parallel-safe
nodes can still express "no dependency between A and B" — this MVP just doesn't *exploit* that
by running them concurrently; it runs the topological order sequentially, which is still correct,
just not maximally fast.

**Cost if wrong:** slower wall-clock for wide DAGs with many independent branches. Concurrency can
be added later as an execution-strategy swap without changing the `Dag`/`DagNode` data model —
the topological-order computation is unaffected by whether execution is sequential or parallel.

## Ruling 2 (what a "node" runs — the DI convention, again): caller-supplied callable, not a new execution engine

**Decision:** `DagNode.run` is a plain Python callable, `Callable[[dict[str, Any]], Any]`, invoked
with a dict of its declared dependencies' outputs. `orchestrate_tasks` does not itself invoke any
LLM, shell command, or MCP tool — it is pure orchestration bookkeeping (topological ordering,
per-node tier resolution via `route_request`, per-node error isolation, audit) over whatever the
caller's callables actually do.

**Why:** this repo has no LLM-invocation client anywhere in `core/` (confirmed during the
memory-fact-layer sub-project's own research — `route_request` is tier-*selection* only). Building
"run a DAG of steps across agents/tools" as if it dispatches to real agents would mean inventing
an agent-invocation protocol this repo doesn't have and Phase 5's own acceptance criterion doesn't
require (the criterion is about the specify/plan/tasks/implement/verify *pipeline* structure, not
about `orchestrate_tasks` itself calling out to live models). Matches `CLAUDE.md` goal 1 (core
stays generic) — a pack or the future spec engine supplies what a node's callable actually does;
`orchestrate_tasks` supplies the graph-execution and governance shell around it.

**Cost if wrong:** if a future consumer genuinely needs `orchestrate_tasks` to invoke a live model
itself rather than delegate via callable, that's an additive change (an optional `model_call`
strategy parameter) — the DAG/node data model and topological-execution logic don't need to
change.

## Ruling 3 (per-node tier resolution): informational, not enforced

**Decision:** each `DagNode` carries an optional `task_type: str = "general"` and
`privacy_sensitive: bool = False`. Before running a node, `orchestrate_tasks` calls
`route_request(RouteRequest(task_type=node.task_type, privacy_sensitive=node.privacy_sensitive),
config=config)` and attaches the resulting `RoutingDecision` to that node's result. The node's
`run` callable receives this decision as part of its input dict (key `"routing_decision"`) so it
*can* act on it (e.g. choose which model to call), but `orchestrate_tasks` does not enforce or
police what the callable actually does with it.

**Why:** consistent with Ruling 2 — routing is a hint the orchestrator computes and hands
downstream, exactly the same relationship `route_request` already has with every other caller in
this repo (nothing calls a model on `route_request`'s behalf; the caller does).

**Cost if wrong:** none — this is additive information a callable is free to ignore.

## Ruling 4 (failure handling): one node's failure skips its dependents, doesn't abort the DAG

**Decision:** if a node's `run` callable raises, that node is marked `status="error"`, the
exception is captured in its result, and every node that (transitively) depends on it is marked
`status="skipped"` without being invoked. Independent branches of the DAG continue to run.
`orchestrate_tasks` itself never raises for a node-level failure — it always returns a
`DagResult`. The one exception: a **structurally invalid DAG** (a cycle, or a node depending on an
id that doesn't exist) raises `ValueError` immediately, before any node runs — this is a caller
programming error, not a runtime failure, matching the precedent `route_request` already sets
(`ValueError("no eligible tiers...")` for a config that can never succeed, verified in the
memory-fact-layer sub-project's own research).

**Why:** matches the "one failure doesn't abort the whole call" convention both Phase 4
sub-projects (code index, memory layer) established and had enforced on them by review. A DAG
modeling e.g. a lint-check node and a test-run node that don't depend on each other shouldn't have
a lint failure prevent the test run from happening and being reported.

**Cost if wrong:** none identified — this is strictly more informative than an all-or-nothing
abort, and matches the plan's own Global Constraints pattern already proven across two prior
sub-projects' final reviews.

## Ruling 5 (audit): one `record_audit` call per node, `result="allow"`/`"error"`

**Decision:** after each node runs (or is skipped), `record_audit(config, actor="orchestrate_tasks",
action=node.id, target=dag.name, result="allow" if status=="done" else "error", detail={...})` —
`"allow"` for a successfully-completed node (mirrors the memory-fact-layer sub-project's own
resolved ruling that `AuditRecord.result`'s `Literal["allow","deny","error"]` has no neutral
"success" value, so "allow" is the closest fit for "this action completed"), `"error"` for a
failed or skipped node.

**Cost if wrong:** cosmetic only, same as the prior sub-project's identical ruling.

## Architecture

```
core/orchestrate/
  __init__.py
  models.py    DagNode, Dag, NodeResult, DagResult (Pydantic v2, except DagNode.run which is a
               plain callable field — Pydantic v2 supports arbitrary callable fields via
               model_config = {"arbitrary_types_allowed": True})
  graph.py     topological_order(dag) -> list[str]  — Kahn's algorithm, raises ValueError on a
               cycle or an unknown dependency id. Pure function, no I/O, independently testable.
  runner.py    orchestrate_tasks(dag, config=None) -> DagResult — the public verb, ties
               topological ordering + route_request + node execution + audit together.
```

## Data flow

`orchestrate_tasks(dag: Dag, config: dict | None = None) -> DagResult`:
1. `topological_order(dag)` — raises `ValueError` immediately on a cycle or a dangling
   `depends_on` reference. No node runs if this raises.
2. `config = config if config is not None else resolve_config_auto()`.
3. For each node id in topological order:
   - If any of its declared dependencies has `status != "done"`: mark this node `"skipped"`,
     `record_audit(..., result="error", detail={"reason": "dependency failed or skipped"})`,
     continue.
   - Else: `route_request(...)` for the node's tier hint; call
     `node.run({dep_id: results[dep_id].output for dep_id in node.depends_on} | {"routing_decision": decision})`
     inside `try/except Exception`. On success: `status="done"`, `output=<return value>`. On
     exception: `status="error"`, `error=str(exc)`.
   - `record_audit` once per node regardless of outcome.
4. Return `DagResult(dag_name=dag.name, nodes={node_id: NodeResult(...), ...})`.

## Global Constraints (carried forward from Phase 4's plans, still binding)

- Core stays language/domain-agnostic — no pack-specific branching in `core/orchestrate/`.
- No verb reads a config file directly — always through `core/config/resolve.py`.
- `resolve_config_auto(root=...)` — this verb has no natural "root" concept (a DAG isn't
  necessarily project-scoped), so it resolves without a root, matching `route_request`'s own
  no-root default. If a future spec-engine consumer needs project-scoped config, it passes
  `config` explicitly (already supported).
- Pydantic v2 models for the typed contract (`DagNode`, `Dag`, `NodeResult`, `DagResult`).
- Every verb call is auditable via `record_audit`, once per node (not once per whole DAG — a DAG
  can have many nodes, each is its own governed action).
- Never crash on malformed input: a cycle/dangling-reference DAG raises immediately and clearly
  (caller error, not swallowed); everything past that point degrades node-by-node, never aborts
  the whole `orchestrate_tasks` call.
- TDD: failing test before implementation, every module.
- Dependency injection: `DagNode.run` is itself the injection point — tests construct DAGs with
  simple lambda/function nodes, no mocking framework needed, consistent with this repo's
  established DI-over-monkeypatching convention.

## Out of scope (deliberately, per the rulings above)

- Concurrent/parallel node execution (Ruling 1).
- `orchestrate_tasks` invoking any LLM/agent/tool itself (Ruling 2) — a caller's callable does.
- Declarative (YAML/JSON) DAG definitions loadable from a pack's `dags/` folder — this spec ships
  the Python-level `Dag`/`DagNode` model only; a declarative-DAG-to-callable-graph loader is a
  natural follow-up once a real pack needs one, not speculative now.
- Retry/backoff policy per node — a failed node is simply marked failed; retrying is a caller
  concern (it can construct a new DAG or re-invoke) for this MVP.
- The spec engine itself (sub-project 2).

## Post-plan follow-ups (log to `docs/BACKLOG.md` if not picked up immediately)

- Sub-project 2: spec engine (`specify/plan/tasks/implement/verify`, EARS artifacts) — needs its
  own brainstorm once this verb ships; will consume `orchestrate_tasks` directly.
- Declarative DAG loading for pack-provided `dags/*.yaml` templates (`ARCHITECTURE.md` §3).
- Parallel execution strategy, if profiling on a real wide DAG ever shows sequential execution is
  a bottleneck (Ruling 1's deferred cost).
- MCP tool exposure for `orchestrate_tasks`, mirroring the other core verbs' eventual MCP
  wrappers.
