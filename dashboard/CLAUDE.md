# dashboard/ — TypeScript/React Web UI

Scoped context. Read root `CLAUDE.md` and `docs/ARCHITECTURE.md` first. Not built until Phase 6 — this file exists now so the plan for it is locked before code starts.

## Responsibility

Renders `gateway/` REST+WS data. Two-mode design per `research/aug2026-findings.md` §7.3:

- **Builder mode** (non-technical): conversational requirements capture, plain-language verify/gate explanations ("I blocked a version because..."), one-click support bundle.
- **Pro mode** (technical): raw spec/diff/policy editing, model-tier pinning, pack/DAG administration, full audit/diagnostics detail.
- **Shared spine**: identical specs/gates/audit/memory underneath — a project started in Builder mode hands off to Pro mode with full history intact.

## Stack

React 18 + Vite + TypeScript, Tailwind + shadcn/ui, TanStack Query for REST, native WebSocket client for live feeds. No server-side rendering needed — this is an authenticated internal tool, not a public site.

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
