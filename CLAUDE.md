# PromptWise Agentic OS — Master Context

> Read this file first, always. It is the project's memory across sessions. Subdirectory `CLAUDE.md` files add scoped detail; they never override the goals or constraints here.

## What this is

An open-source, self-hosted **control plane for AI coding agents** — a "business OS" for agentic software delivery. It sits *under* any coding agent (Claude Code, Aider, Cline, OpenCode, custom) and gives it what none of them ship on their own: enforced verification, governed system actions, persistent cross-session memory, cost-aware routing, and spec-driven workflow — plus a **CMS-style core-engine + installable-pack architecture** so an org runs only the domain modules it needs.

One sentence: *plug in any agent and any model, get routing that cuts cost 60%+, a verification gate that kills "almost-right" code, governed and audited system actions, persistent memory, and spec-driven workflows — all self-hosted, from a laptop to a company VPC.*

**Full vision & research (read before any architectural decision):**
- `docs/research/aug2026-findings.md` — the Aug-2026 problem landscape, problem→solution map, phase plan, Intelligence Packs addendum (Part 7). This is the primary spec.
- `docs/research/v3-implementation-plan.md` — original v3 plan (hardware profiler, model manager, memory layer design detail). Superseded in sequencing by the findings doc, still authoritative for subsystem *design detail* not repeated there.
- `docs/VISION.md` — condensed, always-current restatement of the above two (start here if short on tokens).
- `docs/ARCHITECTURE.md` — core engine + skill-pack system design (the CMS pattern), config layering, plugin contract.
- `docs/MAINTENANCE.md` — health checks, diagnostics, support bundles, upgrade/rollback, troubleshooting mechanism.
- `docs/ROADMAP.md` — phase-by-phase build order with acceptance criteria (mirrors the published artifact).

## Non-negotiable goals (do not drift from these)

1. **Core engine is generic and domain-agnostic.** No stack-specific, industry-specific, or workflow-specific logic lives in `core/`. That logic belongs in a pack. If you catch yourself writing `if language == "python"` in core code, stop — it's a pack.
2. **Everything customizable/configurable without forking.** Behavior changes through config layers (`docs/ARCHITECTURE.md` § Configuration) and pack installation — never through editing core source for a specific customer/org.
3. **Verification gate is mandatory, not optional.** Every agent-produced change passes `verify_output` before it can be marked done. This is the single highest-priority feature — it is the product's main differentiator (Aug-2026 findings, P1).
4. **All system actions are governed and audited.** Every fs/shell/DB/cloud action a pack or agent takes goes through `check_policy` and lands in the hash-chained audit log. No exceptions, no "trusted pack" bypass.
5. **Zero-cost to run.** Every default in Phase 0–6 must work fully offline/local at $0. Cloud model calls are an opt-in escalation tier, never a requirement.
6. **Packs are the only place domain knowledge lives.** Stack packs, database packs, cloud/DevOps packs, architecture packs, migration packs, lifecycle packs — see `docs/ARCHITECTURE.md` § Packs. An org installs 3 packs, not 30.
7. **Maintainability is a first-class module, not an afterthought.** `promptwise doctor`, support bundles, versioned upgrade/rollback, and a troubleshooting KB ship alongside the core engine from Phase 0, not bolted on later.

## Tech stack (locked — see `docs/ARCHITECTURE.md` § Stack Rationale for why)

- **Core engine / gateway:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 + SQLite (Postgres-compatible schema from day one), Qdrant client, LiteLLM (provider abstraction), Alembic (migrations).
- **Dashboard / UI:** TypeScript, React 18, Vite, Tailwind, shadcn/ui, TanStack Query, WebSocket client for live audit/cost feed.
- **Agent integration:** MCP servers via the TypeScript MCP SDK (ecosystem-standard, matches Claude Code/Cursor/OpenCode clients) calling into the Python core over its internal REST/gRPC API; OpenAI-compatible proxy endpoint via LiteLLM for raw model routing from any tool.
- **Local inference:** Ollama. **Sandbox:** Docker (default), gVisor/Firecracker deferred. **Vector store:** Qdrant. **Structured store:** SQLite → Postgres.
- **Verification tooling:** pytest/jest runners, Semgrep, Gitleaks, Ruff/ESLint — orchestrated, not reimplemented.
- **Packaging (packs):** each pack is a self-contained folder (`packs/registry/<pack-name>/`) with a `pack.yaml` manifest — no core code changes to add a pack. See `docs/ARCHITECTURE.md` § Pack Contract.
- **Packaging (delivery):** three tracks, one core — Docker Compose (server, canonical, Phase 0), native desktop app via Tauri (Linux software-center/Flathub + AppImage, Windows `.exe`/`.msi`, Phase 6.5, no Docker required), Debian live-ISO appliance (deferred, Phase 7+). See `docs/ARCHITECTURE.md` §6.

## Repo map

```
CLAUDE.md                    ← this file
docs/
  VISION.md                  ← condensed product vision
  ARCHITECTURE.md            ← core+pack system design, config layering
  MAINTENANCE.md             ← ops/support/troubleshooting mechanism
  ROADMAP.md                 ← phase plan, acceptance criteria
  research/                  ← source research docs (do not edit, historical record)
  superpowers/plans/         ← dated implementation plans (writing-plans skill output)
core/            CLAUDE.md   ← Python core engine: routing, policy, memory, verify, audit, spec engine
gateway/         CLAUDE.md   ← FastAPI HTTP/WS entrypoint, MCP server, OpenAI-compat proxy
dashboard/       CLAUDE.md   ← TS/React web UI (also rendered inside the Phase 6.5 desktop shell, unchanged)
desktop/         (Phase 6.5) ← Tauri shell + sidecar packaging (gateway/Ollama/Qdrant binaries), not created yet
packs/
  registry/                  ← source of installable packs (this repo ships a few reference packs)
  installed/                 ← packs an org has enabled (gitignored per-deployment, seeded at install)
catalog/         model_catalog.yaml   ← model tier definitions (Aug-2026 refresh)
policies/                    ← default policy-as-code rules (fs/shell/DB/cloud)
compose/                     ← docker-compose bundle (canonical delivery format)
scripts/                     ← dev/ops scripts (doctor, support-bundle, migrations)
```

## Working conventions

- **Conventional Commits**, subject + body explaining why, no AI-attribution trailers (global preference, already enforced).
- **TDD**: every core-engine or gateway change follows `superpowers:test-driven-development` — failing test first.
- New subsystem or feature of any size → `superpowers:writing-plans` produces a dated plan in `docs/superpowers/plans/` before code. Small, bounded fixes can skip straight to `cavecrew-builder`/inline edit.
- Cross-cutting or ambiguous work → `superpowers:brainstorming` before planning.
- Before claiming anything "done", run `superpowers:verification-before-completion` — this project's own dogfooded rule (Phase 2's verify gate exists to enforce exactly this).
- Packs never get direct fs/shell/DB access — always through `check_policy`. If a pack seems to need a new capability, add it as a scoped verb in core, not a bypass.

## Current status

Phase 0 complete: compose foundation (Ollama + Qdrant + FastAPI gateway + `promptwise` CLI + doctor) is implemented and verified live via `docker compose up`. Default gateway host port is `8420` (see `compose/.env.example`). Phase 1 complete: hybrid router (`route_request`, RAM watchdog, config-driven tier order), model catalog loader with packaged fallback, and `$/completed-task` cost report are implemented and tested. Next action: write the Phase 2 plan (Verification Gate) per `docs/ROADMAP.md`.
