# dashboard/ — TypeScript/React Web UI

Design: `docs/superpowers/specs/2026-10-17-dashboard-design.md` (read API + auth come first, slices 6a-6e). Scoped context. Read root `CLAUDE.md` and `docs/ARCHITECTURE.md` first. Not built until Phase 6 — this file exists now so the plan for it is locked before code starts.

## Responsibility

Renders `gateway/` REST+WS data. Two-mode design per `research/aug2026-findings.md` §7.3:

- **Builder mode** (non-technical): conversational requirements capture, plain-language verify/gate explanations ("I blocked a version because..."), one-click support bundle.
- **Pro mode** (technical): raw spec/diff/policy editing, model-tier pinning, pack/DAG administration, full audit/diagnostics detail.
- **Shared spine**: identical specs/gates/audit/memory underneath — a project started in Builder mode hands off to Pro mode with full history intact.

## Stack

React 18 + Vite + TypeScript, Tailwind + shadcn/ui, TanStack Query for REST, SSE (EventSource) for live feeds — see docs/superpowers/specs/2026-10-17-dashboard-design.md (D3). No server-side rendering needed — this is an authenticated internal tool, not a public site.

## Build, test, serve (slice 6b, done)

`cd dashboard && npm ci --ignore-scripts && npm test && npm run build`; the gateway serves `dashboard/dist` at `/` (strict CSP, `gateway.dashboard_dir`) when it exists. Dev: `npm run dev` proxies `/api` to `GATEWAY_URL` (default `http://127.0.0.1:8420`). Types come from `dashboard/openapi.json` (`python -m scripts.export_openapi`, then `npm run gen:api`); a Python test fails if the snapshot is stale. Rules enforced by tests: API strings render as text only (no HTML sinks), the credential is in `sessionStorage` only, the live feed uses `fetch` streaming with `Last-Event-ID` resume and is capped at 500 rows. Implemented: credential gate, audit viewer with chain verdict and live feed, diagnostics panel, spec board (stage lanes) and spec detail (requirements, tasks, checks with recorded baseline, acceptance history with independence layers read from the spec engine's audit entries). Routing is a dependency-free hash router (`src/router.ts`: `#/audit`, `#/specs`, `#/specs/<id>`, `#/diagnostics`). Versions are pinned exactly; lockfile is committed.

## Layout (target)

```
dashboard/
  src/
    routes/        chat, audit, policy, packs, diagnostics, spec-board
    components/     shared UI (mode toggle, cost badge, gate-status pill)
    modes/          builder/ and pro/ — mode-specific screens over shared components
    api/            typed client generated from gateway's OpenAPI schema — never hand-write fetch calls
```

## Conventions

- Mode is progressive disclosure over the same components (`docs/ARCHITECTURE.md`'s "shared spine"), not two separate apps.
- Semantic status color (pass/warn/block) is distinct from the product's accent color — see the published artifact's design system for the palette this should match.
- Diagnostics panel (`routes/diagnostics`) is a thin renderer over `run_diagnostics()` + `generate_support_bundle()` — no diagnostic logic duplicated client-side (`docs/MAINTENANCE.md` §4).
