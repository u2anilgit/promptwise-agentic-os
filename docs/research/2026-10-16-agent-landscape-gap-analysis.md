# Agent landscape & gap analysis — 2026-10-16

Source: delegated web research (10 searches, few primary-source fetches) + repo audit. **Most claims are secondary-source; items marked (unverified) need a primary check before driving a decision.**

## Pain points → what we have → gap

| # | Pain point (2026 evidence) | PromptWise today | Gap | Priority |
|---|---|---|---|---|
| 1 | Supply-chain compromise of agent tooling (LiteLLM PyPI 1.82.7/8 malicious 2026-03-24; malicious MCP servers/skills) | LiteLLM is locked stack, unpinned; pack manifest validation only | No dep hash-lock, no known-bad-version check in `doctor`, no pack/MCP signing/SBOM | **P0** |
| 2 | Prompt injection via trusted channels (issue titles, CI actions) | `owasp_scan`-style checks live in the plugin, not core | No untrusted-content tagging in core; fetched text not isolated | **P0** |
| 3 | MCP tool poisoning / hook & config rug-pulls | MCP tool allowlist (Phase 3) | No hash-pin of tool *descriptions*, no change alert, hooks/config changes not audited | **P0** |
| 4 | Destructive actions / over-privileged creds (prod+backups wiped by agent, Apr 2026, unverified) | default-deny policy, JIT, undo buffer for `fs_write` | Only `fs_write` governed; no shell/DB/cloud verbs, no credential broker, no egress deny | **P0** |
| 5 | Cost volatility (up to ~30x token variance same task) | router + `cost_report` | No hard per-task/day caps, no kill switch, no variance alert | P1 |
| 6 | Review/comprehension bottleneck | none | No risk-ranked diff summary / "explain change" | P2 |
| 7 | "Almost-right" code; agent-written tests only prove agent's own belief | verify gate (tests, lint, Semgrep, Gitleaks, failure ledger) | No independence: no mutation check, no spec-derived tests, no separate verifier | **P0** (differentiator) |
| 8 | Spec drift / SDD overhead | spec engine designed, unbuilt | No drift detection spec↔code; graduated ceremony only planned | P1 |
| 9 | Memory poisoning/drift; disputed vendor benchmarks | FTS5+Qdrant+RRF, PII flag | Session leak bug; no provenance/trust tier/TTL; no own eval harness | **P0** (leak) / P1 |
| 10 | Observability; OTel GenAI conventions still "Development" | hash-chained audit | No OTel emission; pin schema version when added | P1 |
| 11 | Agent identity/authz (MCP `iss` param, DCR deprecated) | none | No auth on gateway; no tenant/identity model | P1 team / P0 enterprise |
| 12 | Multi-agent coordination | sequential DAG | No data found; no gap claim | — |

## Standards drift affecting our plan

- **MCP 2026-07-28** (stateless; no initialize/`Mcp-Session-Id`; signed expiring `requestState`; routing headers; `iss` validation; Sampling/Roots/SSE deprecated). Our in-process MCP server and the Phase 6 WebSocket feed must be checked for handshake/session assumptions. `ADOPTION_AND_CAPABILITY_RESEARCH.md` cites the 2025-06-18 spec — outdated. (Dates conflict across sources — verify against spec text.)
- **A2A v1.0**, now under the same foundation as MCP/AGENTS.md — promote from "speculative" to "planned adapter".
- **OWASP**: Agentic Top 10 (ASI01–10, Dec 2025) + new Agent Control Standard (announced 2026-09-02, contents unknown) — map our controls to it.
- **OTel GenAI**: unstable → adapter with pinned schema version.

## Competitors (overlap / what they lack)

Gateways: agentgateway (OSS), AWS AgentCore Gateway, Snowflake/Natoma, Databricks Unity Gateway, Oracle MCP Gateway, AWS MCP Gateway & Registry — all do governed tool calls/policy/audit; none ship verify gate, memory, or spec engine, and most are managed/proprietary. Memory: mem0, Zep/Graphiti, Letta — no governance. Spec: Spec Kit, Kiro, BMAD — no enforcement/routing/audit. Routing: LiteLLM (compromised once), OpenRouter, RouteLLM. Licences/pricing for several are unverified.

**Our defensible niche:** the *only* self-hosted layer combining verify-gate + governed actions + audited memory + spec workflow. Gateways are converging on policy/audit — don't compete there; lead with verification independence and audited memory.

## What best we can make it (target)

1. **Trustworthy core first** (fix before features): hash-locked deps + `doctor` known-bad-version check; LiteLLM pinned or sandboxed behind a thin provider interface; tool-description pinning; memory session isolation; route_request fail-soft.
2. **Independent verification** — the headline differentiator: verifier ≠ author. Spec-derived (EARS) tests, mutation check on changed code, optional second-model verifier; agent-written tests alone never satisfy the gate.
3. **Governed action family**: extend `fs_write` pattern to `shell_exec`, DB, network (deny-by-default egress); credential broker issuing short-lived scoped tokens; protect backup paths from agent write.
4. **Audited memory**: every recall/promotion is an audit decision (already a logged differentiator) + provenance, trust tier, TTL; own retrieval eval set.
5. **Spec engine with drift detection** (stale spec = fail), persisted via SQLAlchemy/Alembic.
6. **Cost control**: hard caps + kill switch + variance alert.
7. **Gateway modernisation**: MCP 2026-07-28 stateless, OpenAI-compatible endpoint, OTel adapter, identity (OIDC/API keys) — in that order; A2A later.
8. **CI + provenance**: CI workflow, SBOM, signed releases/packs.

## Roadmap deltas proposed

- New **Phase 3.5 "Trust hardening"** (items 1, 3 + injection tagging) before Phase 5.2 execution.
- Phase 2 addendum: verification independence (mutation/spec-derived).
- Phase 5.2: add drift detection to acceptance criteria.
- Phase 6 prerequisite: MCP 2026-07-28 check + gateway API contract.
- Phase 8 prerequisite: pack signing + pack-scoped capabilities (F-13).
