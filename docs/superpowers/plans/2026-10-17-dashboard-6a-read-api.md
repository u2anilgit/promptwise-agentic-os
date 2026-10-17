# Dashboard Slice 6a — Authenticated Read API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** A token-protected, read-only `/api/v1` over the audit log, specs, policy and diagnostics, plus a bounded live audit feed, so the dashboard UI (6b+) has real data to render.

**Architecture:** Thin FastAPI router in `gateway/api/`; logic lives in `core/` (`core/audit/read.py`, `core/spec/engine.list_specs`). Auth is a dependency in `gateway/auth.py`. Gateway state paths come from the operator config (`gateway.mcp_guard.operator_config` + `effective_config`), never the project's.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy (existing), pytest + TestClient.

**Spec:** `docs/superpowers/specs/2026-10-17-dashboard-design.md` (D1, D2, D3, 6a acceptance).

## Global Constraints
- Every `/api/v1` route is GET and read-only (a test enumerates the routes). The one exception family is none.
- All routes except `/healthz` require `Authorization: Bearer <token>`; compare with `hmac.compare_digest`; 401 body carries no hint; denials are audited (`api_auth_denied`), rate-limited to one audit record per second so unauthenticated floods cannot grow the log.
- The legacy mutating routes (`/route`, `/cost-report`, `/verify`, `/diagnostics`) get the same dependency (`/verify` runs commands in a caller-chosen cwd, so it must not be anonymous).
- Token file: `gateway.token_path` (default `.promptwise/dashboard_token`), created `secrets.token_urlsafe(32)` on first use, resolved against the gateway cwd, best-effort 0600. Read on every request (rotation = replace the file).
- Browser `EventSource` cannot send headers, so the live feed is consumed with `fetch` streaming; the server still speaks `text/event-stream`, event `id` = byte cursor, so `Last-Event-ID` resume works.
- No logic in `gateway/`; no new dependencies.

## Review Focus
1. Wrong/missing/empty/`Bearer ` token, wrong scheme, token with trailing whitespace → 401, never 500.
2. Audit file with a malformed line, a partial last line (writer mid-append), or CRLF → no crash, partial line not consumed, cursor does not skip it.
3. Tampered audit file → `chain.ok=false` with `broken_at`, not an error response.
4. `limit` out of range (0, negative, 10^9) → clamped/422, never an unbounded read.
5. Spec id with odd characters / unknown id → 404, no path or SQL leakage.

---

### Task 1: Audit reading in core
**Files:** Create `core/audit/read.py`; Test `core/tests/audit/test_read.py` (create dir only if missing — check existing layout first).
**Interfaces — Produces:**
- `class AuditPage(BaseModel)`: `records: list[AuditRecord]`, `next_cursor: int`
- `read_audit(config, after: int = 0, limit: int = 100, action: str | None = None, result: str | None = None) -> AuditPage` — forward from byte offset `after`, skips malformed lines, never consumes a partial trailing line, `limit` clamped to `[1, 500]`.
- `read_audit_tail(config, limit: int = 100, action=None, result=None) -> AuditPage` — newest `limit` matching records in chronological order; `next_cursor` = end of the last complete line.
- `chain_status(config) -> ChainStatus(ok: bool, broken_at: int | None)` in `core/audit/log.py` wrapping `verify_chain`.
- [ ] Failing tests: forward paging with cursor continuity (page1+page2 == all, no dup/skip); filters; malformed line skipped; partial trailing line not consumed and cursor stays before it, then consumed once completed; tail returns last N in order; limit clamp; `chain_status` ok and broken (edit a record's `target`).
- [ ] Implement. Run: `.venv/Scripts/python -m pytest core/tests/audit -q`. Expected: pass.
- [ ] Commit `feat(audit): paged and tail reads over the hash-chained log`.

### Task 2: Spec listing in core
**Files:** Modify `core/spec/store.py`, `core/spec/engine.py`, `core/spec/models.py` if the summary type fits there; Test `core/tests/spec/test_engine_list.py`.
**Produces:** `class SpecSummary(BaseModel)`: `spec_id, request, complexity, stage, created_at, tasks_total, tasks_done`; `list_specs(config=None, root=None) -> list[SpecSummary]` newest first.
- [ ] Failing tests: empty db → `[]`; two specs at different stages with task counts; ordering newest first.
- [ ] Implement `store.list_specs` + engine wrapper (uses `_prepare`). Run spec tests. Commit `feat(spec): list_specs summary view`.

### Task 3: Auth
**Files:** Create `gateway/auth.py`; Test `gateway/tests/test_api_auth.py`; modify `core/config/defaults.yaml` (`gateway.token_path`, `gateway.sse_max_seconds: 300`, `gateway.sse_poll_seconds: 1.0`).
**Produces:** `load_or_create_token(op: dict) -> str`; `require_token` FastAPI dependency (reads `Authorization`, audits denials rate-limited).
- [ ] Failing tests (via a tiny app using the dependency): no header, wrong token, wrong scheme, `Bearer ` empty, trailing-space token → 401 with `WWW-Authenticate: Bearer`; correct token → 200; token file created on first use and stable across calls; denial audited, second denial within 1s not audited again; replacing the file rotates the token.
- [ ] Implement. Commit `feat(gateway): bearer-token dependency with audited, rate-limited denials`.

### Task 4: Read API router
**Files:** Create `gateway/api/__init__.py`, `gateway/api/v1.py`; modify `gateway/app.py`; Test `gateway/tests/test_api_v1.py`; update `gateway/tests/test_app.py` and `conftest.py` (autouse token fixture; existing tests send the header).
**Routes (all GET, under `/api/v1`):** `/audit` (`cursor`, `limit`, `action`, `result`; `tail=true` for initial load) returning `{records, next_cursor, chain}`; `/specs`; `/specs/{spec_id}`; `/policy` (`default_effect`, `rules`); `/diagnostics`; `/events` (SSE).
- [ ] Failing tests: every route 401 without token; audit paging + `chain` + tampered chain; limit bounds; specs list/detail/404; policy shows rules; diagnostics list; **route-enumeration test: every `/api/v1` route is GET only**; legacy `/route` `/verify` `/cost-report` `/diagnostics` 401 without token; `/healthz` open.
- [ ] SSE tests: generator emits records appended after the cursor with `id: <cursor>`; resumes from `Last-Event-ID`; stream ends after `gateway.sse_max_seconds` (set tiny via env) so TestClient can finish; heartbeat comment when idle.
- [ ] Implement using `operator_config()` + `effective_config(op, Path.cwd())` so audit/db paths are the gateway's. Run full gateway tests. Commit `feat(gateway): authenticated read-only /api/v1 (audit, specs, policy, diagnostics, events)`.

### Task 5: CLI, docs, finish
- [ ] `promptwise dashboard token` prints the token (creating it) — test in `scripts/tests`.
- [ ] Update `gateway/CLAUDE.md` (auth, `/api/v1`, SSE), `docs/MAINTENANCE.md` (token location/rotation), `docs/BACKLOG.md` (remove "no auth on HTTP", keep MCP note), `docs/ROADMAP.md` (6a done), root `CLAUDE.md` status line.
- [ ] Full suite in chunks; fresh Opus adversarial review of the branch; fix Critical/Important with RED→GREEN; merge + push.
