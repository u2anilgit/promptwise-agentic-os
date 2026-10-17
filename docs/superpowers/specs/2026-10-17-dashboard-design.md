# Phase 6 Dashboard — Design

Status: proposed (decisions below are my calls; the user delegated them with "go ahead with your best recommendation").
Inputs: `docs/ROADMAP.md` Phase 6, `dashboard/CLAUDE.md`, `docs/research/aug2026-findings.md` §7.3, `gateway/app.py`.

## Intent

The product's value is invisible without a place to see it: which agent did what, which gate blocked what, what a task cost, which specs are stuck. The dashboard is that place. It is a **renderer over the control plane**, never a second implementation of it.

## Goals

1. See every governed action (audit viewer) with the hash-chain verdict shown prominently.
2. See specs and tasks on a board, including per-check baseline state and the independence layers behind each acceptance (`CompletionResult.independence`).
3. See cost and routing per task, and diagnostics, from live data.
4. Builder / Pro modes as progressive disclosure over the same components (shared spine).
5. Run at $0, offline, from the same gateway process. No second server in production.

## Non-goals (this phase)

- Not an editor for policies or specs in v1 (read first; write paths are a later slice with their own review, because every write must go through `check_policy` and the audit log).
- No chat in slice 1 (see slicing). No multi-user accounts, SSO, or RBAC. No cloud hosting.
- No logic duplicated client-side: diagnostics, chain verification, status derivation all stay in `core/`.

## Anti-goals (would make it a failure even if it works)

- A dashboard that widens the attack surface: an unauthenticated read API that leaks audit detail, or any endpoint that mutates state without going through the governed verbs.
- A UI that shows "green" the core did not compute (e.g. client-side re-deriving gate status).
- Rendering untrusted content (memory facts, reviewer notes, tool output) as HTML or markdown that can execute or exfiltrate.

## Key finding: the API does not exist yet

`gateway/app.py` exposes only `/healthz`, `/diagnostics`, `/route`, `/cost-report`, `/verify`. There is no way to read the audit log, list specs, or stream events, and the HTTP surface has **no authentication** (a known limit already in `docs/BACKLOG.md`). So the dashboard's first deliverable is not UI: it is a **read API plus auth**. UI built before that would be a mockup.

## Decisions

### D1. Auth first: a bearer token, loopback by default
- Gateway binds `127.0.0.1` unless the operator sets `gateway.bind`; compose maps the port to the host loopback only.
- All `/api/*` routes require `Authorization: Bearer <token>`. Token is generated on first start into the operator state dir (not the project tree), compared with `hmac.compare_digest`, shown once by `promptwise dashboard token`. The WebSocket/SSE feed takes the token in the first message, never in the URL (URLs land in logs).
- This also closes the "no authentication on the MCP surface" backlog item for HTTP; MCP over stdio is unaffected.
- *Cost if wrong:* single shared token = no per-user attribution. Acceptable for self-hosted single-operator v1; identity is a documented later phase.

### D2. Read API as thin views over core verbs
New router `gateway/api/` (versioned `/api/v1`), each route a pure read:
| Route | Backed by |
|---|---|
| `GET /audit?cursor&limit&action&result` | tail-read of the audit file, paginated; response carries `chain: {ok, broken_at}` from `verify_chain` |
| `GET /specs`, `GET /specs/{id}` | new `list_specs()` in `core/spec/store.py` + existing `spec_status` |
| `GET /cost` | `cost_report` over recorded `CostRecord`s (needs a persisted cost log; see Open items) |
| `GET /diagnostics` | existing `run_diagnostics()` |
| `GET /policy` | read-only render of loaded policy rules |
| `GET /events` (SSE) | new records appended to the audit log, from a byte-offset cursor |
Responses are Pydantic models; the TypeScript client is **generated from the OpenAPI schema** (per `dashboard/CLAUDE.md`), so contract drift fails the build.

### D3. SSE, not WebSocket, for the live feed
Feed is one-directional (server → browser), auto-reconnects, works through proxies, needs no extra dependency. `dashboard/CLAUDE.md` says WebSocket; I am overriding that and updating the file. WebSocket stays available if bidirectional chat needs it later. *Cost if wrong:* a small client swap.

### D4. Untrusted content is data, always
Every string originating from memory, reviewer notes, tool output or audit `detail` is rendered as escaped plain text in a `<pre>`-style component. No `dangerouslySetInnerHTML`, no markdown rendering of those fields. Content already tagged `<untrusted …>` keeps its visible wrapper and an "untrusted" badge. Strict CSP (`default-src 'self'`) set by the gateway when serving the bundle.

### D5. Served by the gateway, built by Vite
Production: `dashboard/dist` served by FastAPI `StaticFiles` at `/`; dev: Vite proxy to the gateway. One process, one port, matches the desktop shell later (Phase 6.5 wraps the same bundle). Node is a build-time dependency only; `dist/` is not committed, the Docker image builds it in a Node stage.

### D6. Stack (locked by CLAUDE.md, restated with my choices inside it)
React 18 + Vite + TypeScript, Tailwind, shadcn/ui, TanStack Query. Tests: Vitest + Testing Library for components, Playwright for one smoke path (token entry → audit list renders → tamper fixture shows chain broken). Lockfile (`package-lock.json`) committed, `npm ci --ignore-scripts` in CI and Docker to keep the supply-chain posture consistent with the Python locks.

### D7. Status colour is computed by core
Gate/chain/baseline states arrive as enums from the API (`pass | warn | block | unverified`); the UI only maps enum → colour/label. Semantic palette distinct from brand accent (per `dashboard/CLAUDE.md`).

## Slicing (each slice shippable, TDD, reviewed, merged on its own)

| Slice | Delivers | Acceptance |
|---|---|---|
| **6a** Read API + auth | `/api/v1` audit, specs, diagnostics, policy, SSE; token; loopback bind; OpenAPI | A request without/with wrong token is 401 and audited; audit pagination correct; a tampered audit file yields `chain.ok=false` with `broken_at`; SSE delivers a record appended after connect; no route mutates state (test enumerates routes) |
| **6b** UI shell + audit viewer + diagnostics | Vite app, token gate, audit table with live feed, chain banner, diagnostics panel | Vitest: renders rows, escapes a hostile `detail` string, shows broken-chain banner; Playwright smoke passes |
| **6c** Spec board | Stage lanes, per-task status, per-check baseline, independence layers | Board matches `spec_status` for a seeded spec across all stages |
| **6d** Cost/routing + Builder/Pro toggle | Cost per completed task, routing badges, mode toggle (plain-language gate explanations in Builder) | Toggle changes disclosure only, not data; explanations come from core reason codes via a lookup table |
| **6e** Chat + first-run wizard | Chat through `/route`, wizard to first chat | Roadmap criterion: clean install → first chat < 10 min (manual timed run recorded) |
| later | Write paths (approve JIT grant, amend check) | Separate design; each goes through governed verbs and audit |

Chat and the wizard are last on purpose: they depend on a working model path and the highest-risk write surface, while 6a–6d deliver the differentiating view (governance made visible) with zero model dependency.

## Open items (resolve in the 6a plan, not blocking)
- **Cost persistence:** `cost_report` takes caller-supplied records; nothing records them. 6a/6d needs an append-only cost log (route decisions → `CostRecord`), small SQLAlchemy table + migration 0004.
- **Audit file growth:** tail-read with a byte-offset cursor now; indexing if files get large.
- **Cross-agent view:** agent identity today is the `actor` string; the "which agent" column is only as good as what callers send. Documented, not solved here.
- Docker Node build stage and CI job are unverifiable locally until Docker is up (same caveat as existing images).

## Risks
- Token in browser storage: use `sessionStorage` (cleared on tab close), never `localStorage`; accepted for loopback single-operator.
- Generated client adds a build step; mitigated by committing the OpenAPI snapshot and failing CI on diff.
