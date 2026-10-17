# Dashboard Slice 6c — Spec Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Checkbox steps.

**Goal:** A board of specs by stage, and a spec detail view showing requirements, tasks, frozen checks with their baseline, and per-task acceptance history including which independence layers backed it.

**Architecture:** No new durable state. The board renders `/api/v1/specs` and `/api/v1/specs/{id}`. Independence layers are already recorded by the spec engine in its audit entries (`complete_task`, `detail.independence`); a new read-only `/api/v1/specs/{id}/history` returns that spec's audit entries (new `target` filter in `core/audit/read.py`). The diagnostics response gets a Pydantic model so it joins the OpenAPI contract. A dependency-free hash router (`#/specs/<id>`) replaces the tab switch.

**Spec:** `docs/superpowers/specs/2026-10-17-dashboard-design.md` (slice 6c). Plan for 6b: `2026-10-17-dashboard-6b-ui-shell.md`.

## Global Constraints
- Read-only; the 6a/6b rules hold: strings render as text only, status colours come from API enums, nothing is recomputed client-side (stage, task status, baseline and independence are rendered as recorded).
- `spec_id` and other path values are `encodeURIComponent`-ed; the hash router never builds a URL from unvalidated data beyond that.
- History is bounded (`limit` <= 200) and filtered server-side by `target == spec_id`.
- No migration, no change to spec engine behaviour.

## Review Focus
1. Hostile request text / requirement text / check command / task id render inert; very long unbroken strings do not break layout.
2. Unknown spec id (`#/specs/nope`) shows "not found", not a crash or an endless spinner; 401 signs out.
3. A spec whose latest `complete_task` audit entry is a denial must not show as accepted; independence comes only from the latest *accepted* completion per task.
4. History for spec A never includes spec B's entries (target filter exactness, prefix ids).
5. Board lanes cover unknown future stage names (shown in an "other" lane rather than dropped).

---

### Task 1: API additions (Python, TDD)
- [ ] `read_audit` / `read_audit_tail` gain `target: str | None` exact-match filter; tests incl. prefix ids (`spec-1` vs `spec-10`).
- [ ] `GET /api/v1/specs/{spec_id}/history?limit=` (limit 1..200, default 100) returns `AuditPage`-shaped `{records, next_cursor}` of that spec's entries, newest last; unknown spec is an empty list (history is audit data, not spec state); requires auth; GET-only (existing route-enumeration test covers it).
- [ ] `/api/v1/diagnostics` gets `response_model=list[CheckResult]`; regenerate `dashboard/openapi.json` and `src/api/schema.d.ts`.
- [ ] Commit.

### Task 2: Router and board (Vitest, TDD)
- [ ] `src/router.ts`: `useHashRoute()` returning `{ name: "audit"|"diagnostics"|"specs"|"spec", id? }`, `navigate()`; invalid hashes fall back to `audit`.
- [ ] `src/features/specs/SpecBoard.tsx`: fetch list, group by stage into lanes (specified, planned, tasked, implementing, verified, other), card = request, complexity, `done/total` tasks, stage badge; click navigates to the detail route.
- [ ] Tests: lanes and counts; unknown stage lands in "other"; hostile request inert; empty state; 401 signs out.
- [ ] Commit.

### Task 3: Spec detail
- [ ] `SpecDetail.tsx`: requirements list; task table (id, status pill, requirement ids, depends on, error text); checks table (requirement, command, files, `expect_baseline`, `baseline` pill: failed=pass-tone "red before work", passed="regression guard" warn, unverified=block); history timeline from `/history`, with independence badges (baseline red / mutation / reviewer) from the latest accepted `complete_task` entry per task, denials shown as denials.
- [ ] Tests per Review Focus 1-4.
- [ ] Commit.

### Task 4: Docs, real-browser check, review, merge
- [ ] Update `dashboard/CLAUDE.md`, `gateway/CLAUDE.md`, `docs/ROADMAP.md`; run gateway + seeded spec in a real browser.
- [ ] Fresh adversarial review; fix Critical/Important RED to GREEN; full suite in chunks + `npm test`; merge and push.
