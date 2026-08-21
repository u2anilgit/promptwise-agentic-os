# Vision (condensed)

Full detail: `research/aug2026-findings.md` (primary spec) and `research/v3-implementation-plan.md` (subsystem design detail). This file is the load-bearing summary — read it when `research/` is too much context.

## Problem (Aug 2026)

1. **Quality** — "almost right" AI code is the #1 dev frustration (66%). Root cause is harness config, not model capability: victory declared early, spec drift, duplicate code, circular retries.
2. **Security** — ~45% of AI-generated code has vulnerabilities; the agent stack itself (MCP tools, fetched content) is now attack surface.
3. **Cost** — heavy AI-automation shops spend $500–2,000/engineer/mo. Fix is harness-level: caching, routing, compaction, batching — not a better model.
4. **Context rot** — poisoning, distraction, confusion, clash degrade long-running agents; cross-session memory is the industry's weakest link.
5. **Workflow** — spec-driven development (constitution → specify → clarify → plan → tasks → implement → analyze) replaced vibe coding as the 2026 default.
6. **Ecosystem gap** — even top OSS agents (OpenHands, Cline, Aider, OpenCode) admit: no unified observability across agents, no portable workflows, governance bolted on not designed in.

## Product

An agent-agnostic **control plane**: routing, verification, governance, memory, and spec workflow as a layer under any coding agent — self-hosted, $0 infra, laptop to VPC.

## What makes this different from "another agent"

We don't compete with OpenHands/Cline/Aider — we make them interchangeable and better. Any MCP-capable agent plugs in and inherits: enforced verify gate, governed/audited actions, persistent memory, cost routing, spec-anchored workflow.

## The CMS extension (this round's addition)

Same pattern as a mature CMS (WordPress/Strapi-class): a **generic core engine** (routing, policy, memory, verify, audit, spec engine — zero domain knowledge) plus **installable Skill/Intelligence Packs** that carry all domain knowledge (stack conventions, database ops, cloud/IaC, architecture patterns, legacy migration, requirements/lifecycle). An org installs the 3–5 packs it needs; the core stays lean and auditable regardless of how many packs exist in the registry. See `ARCHITECTURE.md`.

## The maintenance/support addition (this round's addition)

Ops is not an afterthought: `promptwise doctor` health checks, structured diagnostics, redacted support bundles, a troubleshooting knowledge base (core + per-pack), and versioned upgrade/rollback ship from Phase 0. See `MAINTENANCE.md`.

## Success looks like

- ≥60% cloud spend cut via local-first routing.
- 100% of system actions governed + audited.
- ≥80% top-3 memory retrieval hit rate.
- Verification-gate catch rate tracked and trending toward "most defects caught before they escape."
- An org can go from `docker compose up` to a working, governed, pack-customized agent control plane in under 10 minutes, and self-diagnose problems without filing a support ticket.

## Distribution — three tracks, one core (updated)

Confirmed direction: package first, distro/appliance later, **and** reach users where they already install software — not just self-hosters.

1. **Server/power-user track (Phase 0, canonical, unchanged):** Docker Compose bundle — self-hosted on any Linux box, WSL2, Docker Desktop, or cloud VM/VPC.
2. **Desktop consumer track (new — Phase 6.5):** a native installable app — Linux via Flathub/software-center + AppImage, Windows via `.exe`/`.msi`. Same core engine, no Docker requirement, download-and-run. See `ARCHITECTURE.md` §7.
3. **Distro/appliance track (Phase 7+, unchanged in spirit):** Debian-based live-ISO remaster bundling the Compose stack, for bootable-appliance/offline/kiosk use. Still not a maintained distro fork — see below.

## Explicit non-goals (v1)

- No custom Linux distro/kernel/package repo/desktop shell — the Phase 7+ ISO is a remaster + bundling script, not a maintained distro (revalidated after adding the desktop-app track: the desktop app is a *packaged application*, not an OS).
- No fine-tuning — inference/orchestration only.
- No heavy agent framework (AutoGen/CrewAI/LangGraph) — `orchestrate_tasks` is the DAG runner.
- No GPU passthrough in VM mode.
- Core engine never contains pack-specific/domain-specific logic (see `CLAUDE.md` goal 1).
- ~~No native Windows/macOS ports~~ — **superseded.** Native desktop packaging is now in scope (Phase 6.5) specifically so Linux users can install from a software center and Windows users can download-and-run an installer, without requiring Docker knowledge. macOS native packaging follows the same mechanism once Windows/Linux ship, not blocking either.
