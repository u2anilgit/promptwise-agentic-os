# Adoption and Capability Research

**Review date:** 2026-09-04  
**Question:** What is missing for PromptWise to serve local and paid models, coding agents, desktop chat applications, solo users, teams, enterprises, security-sensitive environments, and scalable deployments?

## Bottom line

The existing architecture has the right control-plane primitives, but it currently targets a technically sophisticated single-user/server operator. To become broadly adoptable, PromptWise needs four product planes around the core:

1. **Compatibility plane** — OpenAI-compatible API, MCP client/server, desktop/IDE adapters, and eventually A2A.
2. **Trust plane** — identity, tenant/project isolation, secrets, approvals, policy simulation, evidence, compliance mapping, and supply-chain verification.
3. **Operations plane** — durable jobs, events, queues, observability, backups, migrations, upgrades, HA, and resource scheduling.
4. **Adoption plane** — installer/wizard, model/provider setup, templates, pack marketplace, documentation, accessibility, localization, and safe defaults.

Without these planes, the current core is useful but remains a toolkit. With them, it can become a portable agent control plane for personal, team, and enterprise use.

## Research signals

- **Superseded in part (2026-10-16): the MCP spec revision 2026-07-28 changed authorization (`iss` validation, Client ID Metadata Documents over Dynamic Client Registration) and made the protocol stateless — see `docs/research/2026-10-16-mcp-2026-07-28-compat.md`. The 2025-06-18 text below is the older baseline.**
- MCP’s HTTP authorization guidance expects OAuth 2.1, protected-resource metadata, authorization-server metadata, PKCE, and resource indicators when authorization is used. This makes a future authenticated remote gateway materially different from the current local stdio-style exposure. [MCP authorization](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)
- A2A is now an open interoperability protocol for independent agents, complementary to MCP’s tool/data connectivity. It is relevant for enterprise delegation and external agent federation, but should be an adapter after the core workflow contract is stable. [A2A specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md)
- LiteLLM’s proxy model demonstrates the adoption baseline for paid-model gateways: authentication, virtual keys, per-user/project budgets, rate limiting, provider fallbacks, spend tracking, and observability callbacks. [LiteLLM documentation](https://docs.litellm.ai/)
- Ollama exposes an OpenAI-compatible API, lowering the integration cost for local inference and existing desktop/IDE clients. [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
- OpenTelemetry is standardizing GenAI/agent semantic conventions, including vocabulary for model calls, tool execution, agents, plans, memory, retrieval, and workflows. PromptWise should emit those semantics rather than invent a private telemetry format. [OpenTelemetry semantic conventions](https://opentelemetry.io/docs/specs/semconv/)
- OWASP’s Agentic AI guidance treats agent autonomy, tool access, memory/context, delegation, and supply-chain behavior as distinct threat surfaces. PromptWise already addresses some of these, but needs a formal threat model and continuous red-team/evaluation loop. [OWASP Agentic AI threats and mitigations](https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/)
- NIST AI RMF and its GenAI Profile provide a use-case-agnostic governance structure that can support solo, regulated, and enterprise deployments without turning PromptWise into a single-industry product. [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework)
- Enterprise deployment needs standard identity federation and provisioning. Keycloak documents OIDC, SAML, and SCIM support as representative capabilities. [Keycloak server administration](https://www.keycloak.org/docs/latest/server_admin/)
- Scaled deployments need explicit workload autoscaling and stateful-data HA rather than simply running more gateway containers. Kubernetes documents HPA/StatefulSet scaling, while PostgreSQL documents replication and failover patterns. [Kubernetes autoscaling](https://kubernetes.io/docs/concepts/workloads/autoscaling/), [PostgreSQL HA](https://www.postgresql.org/docs/16/high-availability.html)
- Reproducible, attestable releases matter when the product governs code and tools. SLSA defines provenance and incremental supply-chain assurance levels. [SLSA specification](https://slsa.dev/spec/v1.2/)

## Capability coverage matrix

| Capability area | Current position | Missing module/features | Priority |
|---|---|---|---|
| Local models | Ollama URL/config and local-first routing exist | Model discovery, download/delete, readiness, context-window metadata, GPU/CPU scheduling, quantization profiles, model pinning and rollback | P0 |
| Paid/cloud models | Catalog/router primitives exist | Provider credential vault, OpenAI/Anthropic/Azure/Vertex/OpenRouter adapters, quotas, retries, circuit breakers, per-tenant budgets, data-residency rules | P0 |
| OpenAI compatibility | Planned but not implemented | `/v1/chat/completions`, `/v1/responses`, embeddings, models, streaming, tool calls, structured output, error compatibility | P0 |
| Coding agents | MCP server exposes only `verify_output` | Full MCP tool/resource/prompt surface, MCP client for outbound tools, capability negotiation, version testing, remote auth | P0 |
| Desktop chat apps | No dashboard/desktop implementation | Browser chat, desktop shell, tray lifecycle, offline mode, import/export, attachments, notifications, safe permission UX | P1 |
| IDE/editor use | No adapters | VS Code extension, JetBrains/terminal integration, project discovery, diff/diagnostics panels, deep links | P1 |
| Identity | No authentication/authorization identity layer | Local profiles, OIDC/SAML, SCIM, MFA/passkeys, service accounts, API keys, RBAC/ABAC, session revocation | P0 enterprise / P1 team |
| Multi-tenancy | Project/root concepts are emerging but not enforced globally | Tenant/org/project hierarchy, quotas, isolation, tenant-scoped keys, audit partitioning, noisy-neighbor controls | P0 enterprise |
| Secrets | No dedicated secrets manager | OS keychain for desktop, environment/secret references, Vault/KMS integration, rotation, redaction, never persist provider secrets in config/audit | P0 |
| Approval workflow | Policy/JIT primitives exist | Human approval inbox, risk-based approval thresholds, four-eyes approval, expiration, delegation, emergency break-glass with audit | P0 |
| Security | Default deny, audit, Semgrep/Gitleaks, PII checks exist | Threat model, prompt-injection isolation, tool provenance/signing, sandbox profiles, egress controls, dependency/image/pack scanning, runtime anomaly response | P0 |
| Compliance | Partial policy/audit foundations | Control mappings for NIST AI RMF, OWASP ASI, SOC 2/ISO 27001 evidence export, retention/legal hold, deletion requests, data residency | P1 |
| Observability | Cost/audit records exist | OpenTelemetry traces/metrics/logs, model/tool latency, token/cost, queue depth, workflow spans, dashboards, alerts, redaction controls | P0 |
| Evaluation | Verification is objective but mainly repository checks | Golden tasks, model/provider regression suites, agent trajectory evals, prompt/pack evals, quality-cost-risk scorecards, canary releases | P0 |
| Workflow execution | Sequential in-process DAG exists | Durable queue, resumable jobs, cancellation, timeouts, retries/backoff, idempotency, concurrency limits, dead-letter queue, worker pools | P0 |
| Persistence | SQLite stores exist; SQLAlchemy/Alembic absent | Relational domain model, migrations, Postgres profile, transaction/outbox pattern, retention and archival | P0 |
| Events/realtime | No event contract | Versioned event schema, replay cursor, WebSocket/SSE gateway stream, webhook delivery, backpressure, tenant filtering | P1 |
| Memory/RAG | FTS5+Qdrant+RRF exists | Session isolation fix, document ingestion, connectors, deletion/TTL, provenance, consent, fact confidence, conflict resolution, memory promotion | P0/P1 |
| Context management | Some rank/context concepts in docs, limited implementation | Token budget manager, compaction, caching, prompt templates, context lineage, retrieval policy by data class, model context negotiation | P1 |
| Pack ecosystem | Loader foundation, empty registry | Pack SDK/CLI, signed manifests, capability scopes, compatibility matrix, dependency resolution, sandboxing, marketplace/index, pack test harness | P1 |
| Configuration | Five-layer design documented | Schema validation, generated config UI, secret references, profiles, environment overlays, config diff/rollback, policy simulation | P0 |
| Deployment | Docker Compose baseline | Dev/single-node/team/HA profiles, Kubernetes Helm/operator, reverse proxy/TLS, air-gapped bundle, backup/restore, upgrades/rollback, resource limits | P1 |
| Reliability | Fail-soft patterns and audit chain exist | SLOs, liveness/readiness, graceful shutdown, leader/worker coordination, disaster recovery, chaos/fault tests | P1 |
| Supply chain | Pack validation and some security checks exist | SBOM, image signing, SLSA provenance, dependency pinning, release attestations, update-channel trust, CVE policy | P1 |
| Accessibility/adoption | No product UI | Guided onboarding, Builder/Pro/Admin modes, accessibility, localization, docs, examples, diagnostics, telemetry opt-in | P1 |
| Governance/product | No explicit edition/license/extension boundary | Community vs enterprise feature boundary, migration guarantees, support channels, feature flags, API deprecation policy | P1 |

## Modules to add

### 1. Provider and model manager

Create a provider abstraction with adapters for local and paid backends. It should own discovery, credentials by reference, capability metadata, pricing, context limits, streaming/tool-call support, health, rate limits, retry/fallback policy, and data-residency classification.

The router should select from **deployments**, not just abstract tiers. A tier may have several deployments, such as local Ollama, Azure OpenAI, and Anthropic. Route decisions should include policy reason, selected deployment, fallback chain, estimated cost, privacy class, and observed outcome.

### 2. Compatibility gateway

Implement an OpenAI-compatible endpoint as the broadest integration point. Support both streaming and non-streaming responses, structured outputs, tool calls, embeddings, model discovery, usage accounting, and provider-compatible error codes. Add explicit API versioning and capability negotiation.

Keep MCP as a separate adapter. Add outbound MCP client support so PromptWise can govern tools exposed by other servers, not only expose its own verification tool. Add A2A later for agent-to-agent task delegation; do not make A2A a dependency of the local single-user path.

### 3. Identity, tenancy, and authorization

Introduce `organization → workspace/project → session → run` as the scope hierarchy. Local mode can use a single implicit organization; enterprise mode must require explicit tenant identity.

Minimum roles: owner, admin, developer, reviewer/approver, auditor, operator, viewer, service account. Model access, pack installation, tool execution, data export, policy changes, and audit access must be independently permissioned.

Use OIDC first, SAML/SCIM as enterprise adapters, and short-lived service credentials for automation. Keep the policy engine as the final action decision point, but enrich its input with authenticated subject, tenant, project, pack, resource, risk, and approval state.

### 4. Durable run and job platform

Move long-running orchestration out of the request process. Add a run record, queue, worker, lease/heartbeat, cancellation token, retry policy, dead-letter state, and event outbox. A small installation can use SQLite plus an in-process worker; a team installation can use Postgres and Redis/NATS; the API contract should remain the same.

Required guarantees: idempotency key, at-least-once worker delivery, deduplicated side effects, resumability after gateway restart, bounded concurrency per tenant/model/tool, and human approval pauses.

### 5. Security and trust center

Add a security module that combines:

- tool/server identity, signing and provenance;
- prompt/content isolation and untrusted-input labels;
- per-tool filesystem, process, network, and secret scopes;
- egress allowlists and network-off profiles;
- sandbox profiles for shell/code execution;
- dependency, container, pack, and model artifact scanning;
- secret rotation and leak prevention;
- policy simulation and “why was this allowed?” explanations;
- red-team regression corpus and threat-model coverage;
- incident response, quarantine, revoke, and replay controls.

### 6. Observability and evaluation plane

Emit OpenTelemetry spans for request, workflow, plan, task, model call, retrieval, tool invocation, policy check, verification, and human approval. Attach cost, latency, model/deployment, tenant/project, risk, and outcome attributes while applying content redaction.

Add an offline evaluation harness covering routing quality, retrieval quality, prompt/pack behavior, tool safety, workflow completion, cost, and regressions. The current test suite validates implementation correctness; it does not yet validate agent quality or operational SLOs.

### 7. Data and memory governance

Extend memory from a fact store into a governed knowledge plane: source provenance, confidence, timestamps, expiration, consent, per-tenant/project/session access, conflict handling, deletion, export, and retention policies. Record every recall decision and make it possible to answer: “which source influenced this action?”

Add connectors for Git repositories, local folders, issue trackers, documentation, tickets, and chat exports behind per-source policies. Ingestion must be explicit or consented, rate-limited, and reversible.

### 8. Configuration and policy UX

Implement schema-backed configuration with profiles such as `local-private`, `developer`, `team`, `enterprise`, and `air-gapped`. Provide CLI validation, dashboard forms, config diff, dry-run, rollback, and environment-variable mapping.

Policy UX should support explain, simulate, test, approve, publish, rollback, and emergency revoke. Store policy versions and link every decision to the exact policy hash.

### 9. Delivery and lifecycle

Add installation modes:

- single-command local desktop;
- Docker Compose developer/server;
- team deployment with Postgres and object storage;
- Kubernetes/Helm enterprise deployment;
- air-gapped/offline bundle;
- CI-only headless mode.

Every mode needs backup/restore, upgrade preflight, migration dry-run, rollback guidance, health checks, resource limits, TLS/reverse-proxy examples, and a support bundle. Desktop updates should be signed and permission-scoped; the Tauri updater documentation already treats updater permissions as an explicit concern. [Tauri updater](https://v2.tauri.app/plugin/updater/)

## Audience fit

| Audience | Must feel easy | Must be configurable | Must be protected from |
|---|---|---|---|
| Non-technical desktop user | one installer, wizard, chat, model health, undo | privacy mode, model choice, data retention | shell surprises, credential loss, confusing approvals |
| Solo developer | CLI/MCP/IDE, local model, fast verify, project memory | provider keys, packs, routing, policies | cloud leakage, broken local setup, lock-in |
| Team lead | shared projects, costs, approvals, audit, templates | budgets, roles, team packs, defaults | runaway spend, inconsistent workflows, unreviewed changes |
| Security/compliance team | evidence, policy simulation, incident controls, immutable exports | retention, residency, controls, allowlists | prompt injection, exfiltration, unsigned tools/packs |
| Enterprise platform team | SSO/SCIM, HA, APIs, metrics, backups, tenancy | deployment topology, IdP, databases, queues, network | noisy neighbors, data mixing, unrecoverable upgrades |
| Agent/platform vendor | OpenAI API, MCP, webhooks, A2A later | capability negotiation, event schemas, adapters | proprietary lock-in, brittle protocol assumptions |

## Recommended priority

### P0 — required for a useful, broadly adoptable product

1. Spec/workflow persistence and API contract.
2. OpenAI-compatible gateway with streaming/tool calls.
3. Provider/model manager for local plus paid deployments.
4. Durable run/job model with cancellation, retries, idempotency, and events.
5. Identity and secrets baseline, even if local mode remains passwordless.
6. Complete MCP surface and authenticated remote transport.
7. Observability/evaluation plane with cost, quality, safety, and latency.
8. Memory/session isolation, provenance, deletion, and audited recall.
9. CI, dependency installation, migrations, backups, and upgrade/rollback.

### P1 — required for team and enterprise adoption

1. OIDC/SAML/SCIM, RBAC/ABAC, tenant quotas, and admin console.
2. Kubernetes/Helm profile, Postgres HA, external object storage, queue workers.
3. Security trust center, signed packs/tools, SBOM/provenance, egress controls.
4. Dashboard, desktop shell, IDE integrations, accessibility and localization.
5. Pack SDK/marketplace and compatibility/test contracts.
6. Compliance evidence mappings and retention/legal-hold workflows.

### P2 — differentiators after the foundation

1. A2A federation and delegated workflows.
2. Multi-agent team patterns and bounded parallel DAG execution.
3. Voice, mobile, browser extension, and rich MCP UI surfaces.
4. Advanced model benchmarking, automatic routing optimization, and team ROI.
5. Migration factory and domain-specific intelligence packs.

## Architectural guardrails

- Keep one semantic core API; adapters may differ, behavior must not.
- Keep local mode fully functional without accounts, cloud, or telemetry.
- Make enterprise features additive: OIDC, Postgres, queues, and external storage should be deployable profiles, not required dependencies for solo users.
- Treat every model, tool, pack, connector, and agent as an untrusted capability until policy and provenance checks approve it.
- Make all long-running work durable; HTTP requests and desktop processes are not reliable workflow storage.
- Use versioned contracts for API, MCP, events, artifacts, packs, policies, and migrations.
- Measure adoption and safety with real fixtures: time-to-first-success, setup failure rate, task completion, cost, leakage, false blocks, recovery time, and upgrade success.

## Suggested next architecture slice

The next implementation should be a **Control Plane Foundation** rather than jumping directly to UI:

1. SQLAlchemy/Alembic domain schema for organization/project/session/workflow/run/artifact/audit references.
2. OpenAPI `/api/v1` and matching MCP wrappers.
3. Provider/deployment abstraction plus OpenAI-compatible `/v1` endpoints.
4. Durable run state, event outbox, idempotency, and cancellation.
5. Auth context and secret references, with anonymous local profile.
6. OpenTelemetry instrumentation and an offline evaluation suite.

That slice unlocks the dashboard, desktop app, enterprise deployment, and pack ecosystem without forcing each future surface to invent its own state model.

## Next plans, effort, tokens, and cost

These are planning estimates, not commitments. They assume one experienced engineer assisted by coding agents, existing Phase 0–4 code is retained, and work includes implementation, tests, review, documentation, and integration. Token figures mean model context/output consumed across planning, coding, debugging, and review; they do not include provider-internal hidden reasoning.

| Phase | Main deliverable | Engineering effort | Model tokens | Model-cost planning range* |
|---|---|---:|---:|---:|
| 0. Foundation hardening | CI/install, dependency lock, orchestration fixes, memory isolation/audit, index fixes, config/gitignore | 1–2 weeks | 80k–150k | $5–$25 |
| 1. Persistence + spec engine | SQLAlchemy/Alembic, workflow/artifact schema, specify/plan/tasks/implement/verify/converge | 3–5 weeks | 180k–350k | $15–$60 |
| 2. Compatibility gateway | OpenAI-compatible `/v1`, streaming, tool calls, embeddings, provider/deployment manager, full MCP adapters | 3–5 weeks | 180k–350k | $15–$70 |
| 3. Durable execution | run records, queue/worker, retries, cancellation, idempotency, event outbox, replay | 2–4 weeks | 140k–280k | $12–$55 |
| 4. Trust + observability | identity baseline, secrets, RBAC/ABAC, approval inbox, OpenTelemetry, eval harness, security center | 4–7 weeks | 250k–500k | $25–$100 |
| 5. User surfaces | dashboard, chat, diagnostics, cost/audit views, desktop shell, onboarding, accessibility | 4–7 weeks | 250k–500k | $20–$90 |
| 6. Enterprise delivery | Postgres/HA, object storage, Kubernetes/Helm, backups, upgrades, air-gapped profile, signed releases | 4–8 weeks | 250k–550k | $25–$120 |
| 7. Ecosystem | pack SDK/marketplace, reference packs, IDE integrations, A2A adapter, connectors | 5–10 weeks | 300k–700k | $30–$160 |

**Combined product path:** approximately **26–48 engineer-weeks**, **1.6M–3.4M model tokens**, and **$147–$680 in model usage** for agent-assisted development. Parallel work can reduce calendar time but increases coordination and integration risk. Human labor, paid model API usage by end users, cloud infrastructure, code-signing certificates, hosted observability, and marketplace operations are excluded.

\*Cost ranges are intentionally broad because the mix matters more than raw token count. PromptWise’s current estimate for a small 345-token planning exchange routed to `claude-opus-4-8` was **$0.018975**; its static advisory comparison estimated **$0.00129375** for Gemini 1.5 Pro, which is not live pricing and must be rechecked before budgeting. Large code-edit sessions can cost much more than a short planning prompt. Use medium/cheap tiers for extraction, scaffolding, tests, and routine fixes; reserve high-tier models for architecture, security review, difficult debugging, and release decisions.

### Recommended execution order

1. **Now:** Foundation hardening plus CI. This reduces risk and makes all later estimates trustworthy.
2. **Next:** Persistence/spec engine and stable API contracts. This creates the durable product spine.
3. **Then:** Provider manager and OpenAI-compatible gateway. This unlocks paid models, local models, desktop apps, and most third-party clients.
4. **After:** Durable jobs/events and observability/evaluation. These are prerequisites for reliable long-running workflows and enterprise operations.
5. **Then:** Identity/security/approval controls and dashboard. Build the UI against the stable contracts.
6. **Finally:** Desktop packaging, Kubernetes/HA, packs, connectors, and A2A federation.

### Suggested first release milestones

| Milestone | User-visible outcome | Exit criteria |
|---|---|---|
| M1 — Core reliable | Existing core works from a clean install | CI green, dependencies reproducible, no known P0 defects, doctor actionable |
| M2 — Governed workflow | User submits a feature and receives spec, tasks, implementation evidence, and verification result | Durable workflow state, EARS artifacts, audit-linked transitions, converge report |
| M3 — Universal gateway | Existing OpenAI-compatible clients and MCP agents can use local or paid models | Streaming/tool calls, auth hooks, usage/cost records, provider fallback tests |
| M4 — Team-ready | Multiple users/projects can collaborate safely | OIDC or local auth, roles, tenant/project isolation, approvals, event replay, OTel |
| M5 — Adoptable product | A non-technical user can install and complete a first chat/workflow | Installer/wizard, desktop or browser UI, safe defaults, backup/upgrade path |
| M6 — Enterprise profile | Operators can deploy and recover the system at scale | Postgres/HA profile, worker scaling, backups/restore, signed artifacts, compliance evidence |

### Cost-control rules for implementation

- Cache stable repository summaries, architecture decisions, API schemas, and pack contracts; do not resend the entire repository for every task.
- Use PromptWise routing by task class: cheap/local for extraction and routine tests, medium for ordinary coding, high-tier only for architecture, security, and difficult failure analysis.
- Make model usage visible by project, user, workflow, provider, and task; set advisory budgets before enabling cloud escalation.
- Prefer deterministic tests and static analysis over repeated model self-critique.
- Use short, anchored context shards for subsystem work and archive completed decisions rather than carrying the entire conversation.
- Re-estimate each milestone after the first real implementation slice; actual token usage will be more reliable than early estimates.
