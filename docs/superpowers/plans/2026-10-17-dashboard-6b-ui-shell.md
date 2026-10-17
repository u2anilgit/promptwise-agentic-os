# Dashboard Slice 6b — UI Shell, Audit Viewer, Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Checkbox steps.

**Goal:** A Vite + React + TypeScript app, served by the gateway, that shows the live audit log with the hash-chain verdict and the diagnostics panel, behind the 6a credential.

**Architecture:** `dashboard/` is a static SPA. Types come from the gateway's OpenAPI snapshot (`dashboard/openapi.json`, guarded by a Python test so it cannot drift). Live feed is `fetch` streaming of `/api/v1/events` (EventSource cannot send the Authorization header). The gateway mounts `dashboard/dist` at `/` with a strict CSP when it exists.

**Tech Stack:** React 18, Vite 5, TypeScript, Tailwind 3, TanStack Query 5, openapi-typescript, Vitest + Testing Library (jsdom). Exact versions pinned, `package-lock.json` committed, installs use `--ignore-scripts`.

**Spec:** `docs/superpowers/specs/2026-10-17-dashboard-design.md` (D3 to D7, slice 6b).

## Global Constraints
- Every string from the API (audit `detail`/`target`/`actor`, diagnostics `message`) renders as escaped text. No `dangerouslySetInnerHTML`, no markdown, no `innerHTML` (a test greps `src/` for them).
- The credential lives in `sessionStorage` only, never `localStorage`, never in a URL.
- Status colours come from API enums (`allow|deny|error`, `PASS|WARN|FAIL`, chain `ok`); UI only maps enum to label/colour. Semantic palette separate from the accent.
- No logic duplicated from core: chain verdict and diagnostics are rendered, never recomputed.
- shadcn/ui is a copy-in pattern; 6b hand-writes the three primitives it needs (Badge, Card, Table styles) in that style rather than pulling the CLI.
- Builder/Pro toggle, spec board, cost, chat are later slices.

## Review Focus
1. Hostile audit text (`<img onerror>`, `<script>`, very long unbroken strings) renders inert and does not break layout.
2. Wrong credential: clear message, credential cleared, no retry loop; 503 shows "credential unavailable" distinctly.
3. Stream drop or server-ended stream (it ends every `gateway.sse_max_seconds`): reconnect with `Last-Event-ID`, no duplicate rows, no gap.
4. Broken chain: prominent banner naming the record index; never silently shown as OK on an error response.
5. Unbounded growth: the live list is capped (500 rows) so a long-open tab does not eat memory.

---

### Task 1: Scaffold and OpenAPI contract
- [ ] `dashboard/package.json` (exact pins), `tsconfig.json`, `vite.config.ts` (dev proxy `/api` + `/healthz` to the gateway), `tailwind.config.js`, `postcss.config.js`, `index.html`, `src/main.tsx`, `src/App.tsx` placeholder, `.gitignore` for `node_modules` and `dist`.
- [ ] `scripts/export_openapi.py` writes `dashboard/openapi.json` from `gateway.app.app.openapi()`; failing Python test `gateway/tests/test_openapi_snapshot.py` asserts the committed snapshot equals the live schema (RED before the file exists), then generate it. `npm run gen:api` runs `openapi-typescript` to `src/api/schema.d.ts` (committed).
- [ ] Commit `feat(dashboard): scaffold Vite React app and OpenAPI contract`.

### Task 2: API client, credential store, SSE parser (Vitest, RED first)
- **Produces:** `src/api/credential.ts` (`getCredential/setCredential/clearCredential`, sessionStorage only), `src/api/client.ts` (`apiGet<T>(path)`, throws `ApiError{status}`; 401 clears the credential), `src/api/sse.ts` (`parseSse(chunk-stream) -> AsyncIterable<{id?, event, data}>` handling split chunks, CRLF, comments, multi-line data) and `streamAudit({after, signal, onRecord, onState})` with reconnect from the last id.
- [ ] Tests: credential never touches localStorage; 401 clears it; parser handles a record split across chunks, heartbeat comments, CRLF; reconnect resumes with `Last-Event-ID` and drops duplicate record ids.
- [ ] Commit.

### Task 3: Audit viewer
- **Produces:** `src/features/audit/AuditView.tsx`, `ChainBanner.tsx`, `AuditTable.tsx`, `useAuditFeed.ts`.
- [ ] Tests: tail load renders rows newest first; live record is prepended once; list capped at 500; `chain.ok=false` shows the banner with the index; hostile strings render as text nodes (no `img`/`script` elements in the DOM); long unbroken target does not overflow (class `break-all`); filter by action/result refetches.
- [ ] Commit.

### Task 4: Diagnostics panel, shell, token gate
- [ ] `TokenGate` (enter credential, validate against `/api/v1/policy`, 401 message vs 503 message), `Shell` nav (Audit, Diagnostics), `DiagnosticsView` with PASS/WARN/FAIL pills and refresh.
- [ ] Tests: gate stores in sessionStorage and shows an error on 401; 503 distinct message; diagnostics pills map enum to label; source grep test for forbidden HTML sinks.
- [ ] Commit.

### Task 5: Gateway serves the bundle
**Files:** `gateway/app.py`, `gateway/tests/test_dashboard_static.py`, default `gateway.dashboard_dir: dashboard/dist`.
- [ ] Failing tests: with a tmp `dist/index.html`, `GET /` returns it with `Content-Security-Policy: default-src 'self'; ...`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` for index; `/api/v1/*` and `/healthz` unaffected; no `dist` means `/` is a 404 and the app still starts; path traversal (`/..%2f..`) cannot escape `dist`.
- [ ] Implement with `StaticFiles(html=True)` mounted last, headers via a small middleware limited to non-API paths.
- [ ] Commit.

### Task 6: Docs, build check, review, merge
- [ ] `npm run build` and `npm test` green; run the gateway against the built bundle and check the page in a real browser if the browser tools work (otherwise say so).
- [ ] Update `dashboard/CLAUDE.md`, `gateway/CLAUDE.md`, `docs/MAINTENANCE.md` (build/serve steps), `docs/BACKLOG.md` (Playwright smoke deferred, Dockerfile Node stage), `docs/ROADMAP.md`.
- [ ] Fresh Opus adversarial review; fix Critical/Important RED to GREEN; full suite in chunks plus `npm test`; merge and push.
