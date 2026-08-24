# Design: Ingestion Sweep (Phase 4 sub-project 3 of 3)

Scope: Phase 4 sub-project 3 of 3 ("Memory & code context" in `docs/ROADMAP.md`). Sub-project 1
(code index) and sub-project 2 (memory/fact layer) are done, merged `deab912`/`3f56319`. This
sub-project is what `docs/BACKLOG.md` describes as "the daemon that keeps the code index and
memory layer fresh without manual reindex/record_memory calls."

Written autonomously per explicit user instruction ("keep going ... full autonomous mode") —
design decisions below are rulings, not interactive Q&A. Each is recorded with its cost-if-wrong,
same convention as the SDD ledger's rulings. Bias applied throughout: the **lower-risk** option at
every fork, per the same instruction's "safer."

## Problem

Both `query_code_index` and `record_memory` are on-demand verbs — nothing calls them unless a
caller does. `docs/research/aug2026-findings.md`'s original framing names an "ingestion daemon"
that keeps things fresh automatically: watched folders, session capture, scheduled reindex.

## Ruling 1 (scope/risk): ship a sweep *verb*, not a background process

**Decision:** this sub-project ships `run_ingestion_sweep(root, session_texts=None, config=None,
...) -> IngestionResult` — a single idempotent function a caller invokes once. It does NOT start
a thread, spawn a subprocess, register a filesystem watcher, or run on any implicit schedule.
Scheduling (cron, systemd timer, Windows Task Scheduler, or a future gateway-hosted scheduler) is
an ops concern outside `core/`, invoking this verb the same way any of the project's other
on-demand verbs are invoked.

**Why (the "safer" bias):** a real background daemon is materially riskier and more complex than
everything shipped in Phases 0-4 so far — it needs process supervision, a filesystem watcher
library (a new dependency and a new class of resource-exhaustion/race bugs, e.g. the exact
symlink-cycle and permission-error bug classes the code-index sub-project's two review rounds
already found and fixed *once*, that a long-running watcher would face continuously rather than
per-call), and a decision about how it authenticates/authorizes itself as an actor distinct from
an interactive session (goal 4's audit model assumes an actor; a daemon's actor identity is an
open design question nothing in this repo answers yet). None of that risk is required to make
"the index/memory stay fresh" true — a caller (human, cron, or later a gateway scheduler) invoking
one idempotent verb on a cadence achieves the same freshness with zero new attack surface, zero
new dependencies, and full reuse of the two sub-projects' own already-reviewed error handling.

**Cost if wrong:** if a literal persistent daemon turns out to be genuinely required later (e.g.
sub-second freshness needed), this sweep verb is exactly the function such a daemon would call in
its loop — no wasted work, just an additional thin wrapper.

## Ruling 2 (session capture / folder watching): explicit input, not automatic capture

**Decision:** `run_ingestion_sweep` takes an optional `session_texts: list[str] | None` parameter
— raw text blocks the CALLER supplies (e.g. a Claude Code hook's session-end summary, a
CI job's commit message, anything). Each is forwarded to `record_memory(text, scope="session",
session_id=..., root=root)`. This sub-project does NOT read conversation transcripts, watch
folders, or infer what counts as session content — that inference is exactly the kind of
judgment call goal 4's audit/policy model exists to gate, and this repo has no defined policy
surface for "which files/conversations may be auto-ingested" yet.

**Why (the "safer" bias):** automatic folder-watching or transcript-scraping reads arbitrary
content and, per Decision 4 of the memory-fact-layer spec, PII flagging is best-effort regex —
auto-ingesting unknown content at unknown volume is a real privacy/cost surface this repo's
current governance model isn't built to bound yet (no per-source policy, no rate limit, no
consent flow). Requiring the caller to hand over exactly the text to ingest keeps this sub-project
inside what's already reviewed and governed (record_memory's own PII flagging still applies to
whatever text is handed in).

**Cost if wrong:** real automatic session capture / watched-folder ingestion becomes a follow-up
sub-project once a policy model for "what may be auto-ingested" exists — logged to
`docs/BACKLOG.md` below, not silently dropped.

## Ruling 3 (code index freshness): reuse `query_code_index`'s existing reindex side effect

**Decision:** no new reindex verb in `core/index/`. `run_ingestion_sweep` triggers a full
incremental reindex by calling `query_code_index("", root=root, config=config)` and discarding
the (irrelevant, everything-matches) result — `query_symbol`'s `LIKE '%{symbol}%'` with an empty
symbol matches every row, but the walk+reindex step that runs *before* the query answers is the
only side effect this call is for. This was hand-verified against the real `query_symbol` SQL
(`core/index/store.py:71-82`) before writing this decision, not assumed.

**Why:** avoids touching `core/index/` at all (zero regression risk to an already-reviewed,
already-merged sub-project) and avoids a second, parallel "trigger a reindex" code path that could
drift from `query_code_index`'s own walk logic.

**Cost if wrong:** wasted CPU on the throwaway query result (`query_symbol`'s SQL still executes
a full-table scan after the reindex) — negligible for any realistically-sized project, and easy to
swap for a dedicated `reindex_code_index(root)` verb later if profiling ever shows it matters.

## Architecture

```
core/ingestion/
  __init__.py
  models.py    IngestionResult (Pydantic v2): root, code_index_refreshed, facts_recorded,
               facts_failed, errors: list[str]
  sweep.py     run_ingestion_sweep(root, session_texts=None, session_id=None, config=None,
               http_post=default_http_post, qdrant_client=None) -> IngestionResult
```

One file beyond the model, deliberately — this sub-project is thin composition over two
already-built sub-projects, not new domain logic. Matches the "don't pre-create structure you
don't need yet" convention in `core/CLAUDE.md`.

## Data flow

`run_ingestion_sweep(root, session_texts=None, session_id=None, config=None, ...)`:
1. `query_code_index("", root=root, config=config)` — reindex side effect. Wrapped in
   `try/except Exception`: a failure here is appended to `errors`, `code_index_refreshed=False`,
   and the sweep continues to step 2 rather than aborting (same "one failure doesn't abort the
   whole call" convention both consumed sub-projects already established).
2. For each text in `session_texts or []`: `record_memory(text, scope="session",
   session_id=session_id, root=str(root), config=config, http_post=http_post,
   qdrant_client=qdrant_client)`. A failure for one text block is caught and appended to `errors`
   (with an index so the caller can identify which block), incrementing `facts_failed` rather than
   aborting the remaining blocks.
3. Returns `IngestionResult(root=str(root), code_index_refreshed=<bool>, facts_recorded=<int>,
   facts_failed=<int>, errors=[...])`.

No new SQLite table, no new Qdrant collection, no new HTTP surface — purely a caller of the two
existing verbs' public interfaces (`query_code_index(symbol, kind=None, root=None, config=None)`,
`record_memory(text, scope, root=None, session_id=None, config=None, http_post=..., 
qdrant_client=None)`), both already reviewed and merged.

## Global Constraints (carried forward, still binding)

- Never crash on malformed input: a code-index failure or a per-text `record_memory` failure are
  both handled states (accumulate in `errors`, keep going), never exceptions that abort the whole
  sweep.
- No verb reads a config file directly — `config` is threaded through to both consumed verbs
  exactly as received (or resolved once via `resolve_config_auto(root=root)` if not supplied, same
  pattern as both consumed sub-projects).
- Pydantic v2 model for the typed contract (`IngestionResult`).
- TDD, failing test before implementation.
- Dependency injection for network calls (`http_post`, `qdrant_client` pass straight through to
  `record_memory`, not reinvented here).

## Out of scope (deliberately, per the rulings above)

- Any actual scheduling/daemonization (Ruling 1).
- Automatic session-transcript capture or filesystem watching (Ruling 2).
- A dedicated code-index reindex verb (Ruling 3).
- Rate limiting / cost bounding on `session_texts` volume — the caller controls what it passes in;
  no volume cap is enforced here. Follow-up once a real automatic-capture caller exists.

## Post-plan follow-ups (log to `docs/BACKLOG.md` if not picked up immediately)

- A reference ops recipe (cron entry / systemd timer / Task Scheduler task / gateway-hosted
  scheduler) that calls `run_ingestion_sweep` on a cadence — this spec ships the verb, not the
  invocation cron job.
- Automatic session-transcript capture and watched-folder ingestion, once a policy model exists
  for "what may be auto-ingested" (Ruling 2's deferred real daemon behavior).
- MCP tool exposure for `run_ingestion_sweep`, mirroring the other two sub-projects' eventual MCP
  wrappers.
