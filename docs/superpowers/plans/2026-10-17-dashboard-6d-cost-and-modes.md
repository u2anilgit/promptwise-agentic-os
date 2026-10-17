# Dashboard Slice 6d — Usage/Cost and Builder/Pro Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Checkbox steps.

**Goal:** Make `$/completed-task` and routing visible: agents report token usage through a governed verb, it is persisted with the cost fixed at record time, and the dashboard shows it; plus a Builder/Pro mode toggle that changes disclosure, not data.

**Architecture:** `usage_event` table (Alembic 0004). `core/routing/usage.py` holds `record_usage` and `usage_report` (cost from the catalog tier at record time; reports aggregate in SQL). `record_usage` is exposed as the 13th governed MCP tool (the only ingestion path: core calls no LLM, so only the agent knows its usage). Read side: `GET /api/v1/usage`. UI: Cost view and a mode context. Builder mode swaps raw detail/hashes for plain sentences from a lookup table keyed by core reason codes; unknown codes show as-is.

**Spec:** `docs/superpowers/specs/2026-10-17-dashboard-design.md` (slice 6d).

## Global Constraints
- Usage is **self-reported by agents** (the gateway does not see model traffic). The UI says so next to every figure; nothing implies measured spend.
- Cost is computed once at record time from the catalog tier and stored; later catalog edits never rewrite history. Unknown tier is rejected, never guessed.
- Bounds: tokens `0..1_000_000_000` integers; strings (`agent`, `task_ref`, `spec_id`) <= 200 chars; report window 1..365 days; recent events <= 50; every record is audited.
- Read API stays GET-only. All strings render as text. Mode lives in `sessionStorage` (no `localStorage`). Mode never changes what data is fetched or hides a denial/warning/broken-chain alert.
- Builder explanations are a lookup table in the UI keyed by core reason codes; unknown codes fall back to the raw code (never invented prose).

## Review Focus
1. Negative / huge / non-integer tokens, NaN, tier not in catalog, oversized strings: rejected with a clear error and no row written.
2. Concurrent writers to `usage_event` (SQLite busy) do not lose events or crash the tool.
3. `cost_per_task` with no `task_ref`s is `null`, not 0 or a division error; a task_ref reused by two agents is one task.
4. Builder mode never hides a broken chain, a denial, or "baseline not proven".
5. Window filtering uses event time, and an empty window yields zeros, not errors.

---

### Task 1: Persistence and core verbs (pytest, TDD)
- [ ] Migration `0004_usage_event`; `core/routing/tables.py` (`UsageRow`); register in `core/migrations/env.py`; update migration/db tests for head `0004`.
- [ ] `core/routing/usage.py`: `record_usage(tier, tokens_in, tokens_out, agent="unknown", task_ref=None, spec_id=None, config=None, root=None) -> UsageEvent` and `usage_report(days=7, config=None, root=None) -> UsageReport` (totals, by_tier, by_agent, `cost_per_task_usd | None`, recent events).
- [ ] Tests per Review Focus 1, 3, 5; audit entry written per record.
- [ ] Commit.

### Task 2: Governed MCP tool + CLI
- [ ] `record_usage` tool in `gateway/mcp_server.py` through `run_governed`; `promptwise pin-tools`; registry/consistency/stdio tests updated for 13 tools.
- [ ] `promptwise usage record|report` CLI.
- [ ] Commit.

### Task 3: Read API
- [ ] `GET /api/v1/usage?days=` returning `UsageReport` plus `tiers: [{name, requires_cloud}]` from the catalog (for local/cloud badges); auth, bounds (days 1..365), GET-only; regenerate OpenAPI snapshot and TS types.
- [ ] Commit.

### Task 4: Frontend (Vitest, TDD)
- [ ] `src/mode.tsx`: `ModeProvider`/`useMode` (`builder|pro`, default `pro`, sessionStorage), toggle in the header.
- [ ] `src/explain.ts`: reason-code/action lookup (`explainReason`, `explainAction`) with raw fallback; tests for known codes (`acceptance_check_failed:R1`, `baseline_not_proven:R1`, `checks_failing:R2`, `mcp_root_denied`, `api_auth_denied`) and unknown.
- [ ] `src/features/cost/CostView.tsx`: totals, $/task (or "no task references yet"), by tier with local/cloud badge, by agent, recent events, "self-reported" note; route `#/cost`.
- [ ] Builder mode applied to Audit (sentence instead of raw detail/hash columns), Spec detail (sentences for reasons), Cost (hides token counts). Alerts stay.
- [ ] Commit.

### Task 5: Docs, real-browser check, review, merge
- [ ] Docs (`dashboard/CLAUDE.md`, `gateway/CLAUDE.md` tool count, `docs/MAINTENANCE.md` usage section, ROADMAP); real browser pass with seeded usage; adversarial review; fix pass; full suites; merge and push.
