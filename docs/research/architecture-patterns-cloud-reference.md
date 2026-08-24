# Architecture Patterns & Cloud Solutions — Reference

> Research pass, 2026-08-24. Feeds a future **architecture-advisor** capability (pack or MCP verb) that recommends a pattern + cloud stack from user context. Not implemented yet — see `docs/BACKLOG.md`.

## Sources
- [Types of Software Architecture Patterns — GeeksforGeeks](https://www.geeksforgeeks.org/software-engineering/types-of-software-architecture-patterns/)
- [Enterprise Software Architecture Patterns — Rishabh Software](https://www.rishabhsoft.com/blog/enterprise-software-architecture-patterns)
- Cloud service/deployment models: [Motadata](https://www.motadata.com/blog/types-of-cloud-computing-services-deployment-models), [Encore](https://encore.dev/articles/iaas-paas-baas), [IBM](https://www.ibm.com/think/topics/iaas-paas-saas), [Azure](https://azure.microsoft.com/en-us/resources/cloud-computing-dictionary/what-are-iaas-paas-and-saas/)
- Provider comparison: [CloudZero 2026](https://www.cloudzero.com/blog/cloud-service-providers/), [KodeKloud](https://kodekloud.com/blog/aws-vs-azure-vs-gcp/), [DigitalOcean](https://www.digitalocean.com/resources/articles/comparing-aws-azure-gcp)

## Software architecture patterns — decision table

| Pattern | Core idea | Best fit context | Watch-out |
|---|---|---|---|
| Layered (N-tier) | Presentation/business/data layers | Traditional enterprise apps, small team, quick start | Bypassed layers → tight coupling |
| Client-Server | Central server, many clients | Web apps, email, file share | Single point of failure |
| Event-Driven | Events trigger decoupled handlers | Real-time analytics, IoT, fraud detection | Hard system-wide transactions/error handling |
| Microkernel (plug-in) | Minimal core + plug-ins | IDEs, browsers, extensible platforms | Plug-in compatibility complexity |
| Microservices | Independent deployable services | E-commerce, streaming, fast-scaling teams | Distributed-system tax: data consistency, ops overhead |
| Space-Based | Shared in-memory tuple space, no central DB | High-concurrency, unpredictable spike load (ticketing, gaming) | Weak transactional guarantees |
| Master-Slave | One controller, many workers | DB replication, load balancing, sensor nets | Master failure = data loss risk |
| Pipe-Filter | Sequential filter stages | ETL, compilers, image pipelines | Backpressure/error propagation across stages |
| Broker | Intermediary routes requests | EAI, message-driven, IoT | Broker becomes bottleneck/SPOF if not scaled |
| Peer-to-Peer | No central authority, every node client+server | File-sharing, blockchain, decentralized comms | Consistency/coordination is hard |
| Serverless (FaaS) | Provider runs infra, functions on-demand | Event-driven APIs, bursty/variable load, fast ship | Cold starts, vendor lock-in, hard to debug distributed |
| CQRS | Split read model from write model | High-read-volume + complex-write systems, analytics/finance | Sync complexity, overkill for CRUD apps |
| DDD (Domain-Driven Design) | Model = ubiquitous language of the business domain | Complex evolving business rules (finance, healthcare, logistics) | Needs real domain-expert access, slow to start |
| Hexagonal (Ports & Adapters) | Core logic isolated behind ports; adapters plug in tech | Long-lived systems, frequent integration/tech churn, high testability need | Extra indirection layer, overkill for throwaway apps |
| SOA | Reusable services over standard interfaces (enterprise-wide) | Multi-app enterprises, legacy integration | Governance overhead, comms latency |

**Combinable, not exclusive** — e.g. this repo already is layered-core + microkernel-pack + event-adjacent (MCP verb calls) + hexagonal-ish (core never touches pack internals directly).

## Cloud service models

| Model | You manage | Provider manages | Fit |
|---|---|---|---|
| IaaS | OS up (runtime, app, patches) | Hardware, virtualization, network | Full control needed, custom stacks, migration lift-and-shift |
| PaaS | App code + config | OS, runtime, scaling | Fast dev cycles, don't want ops burden |
| SaaS | Just usage/config | Everything | Off-the-shelf business function, not core differentiator |
| FaaS (serverless) | Function code only | Everything else, per-invocation scaling | Event-driven, bursty, pay-per-use |

## Cloud deployment models

- **Public** — shared infra, provider-managed, lowest ops burden, least control.
- **Private** — dedicated single-tenant, highest control/compliance, highest cost/ops.
- **Hybrid** — split by workload sensitivity/latency (e.g. this project's own local-first + optional cloud escalation tier is a hybrid pattern already).
- **Multi-cloud** — avoid vendor lock-in, optimize per-workload cost/capability; 87% of orgs run multi-cloud as of 2026 — but adds real ops/governance cost, don't default to it without a driving reason.

## Provider snapshot (2026)

| Provider | Market share | YoY growth | Strength | Best-fit driver |
|---|---|---|---|---|
| AWS | ~30-31% | +19% | Broadest service catalog (200+), largest ecosystem | Default choice, no strong opinion needed, max service breadth |
| Azure | ~23-25% | +40% | M365 integration, OpenAI exclusive partnership, most compliance certs | Enterprise already on Microsoft stack, regulated industries, OpenAI-model access |
| GCP | ~11-13% | +63% | GKE (best K8s), BigQuery, cheapest AI compute (5-10% under AWS/Azure) | Data/analytics-heavy workloads, K8s-native, AI/ML cost-sensitive |

## How to use this (recommendation heuristic, for the future advisor)

Ask/derive 4 things from user context, then map:
1. **Team size & ops appetite** → small/no-ops team → PaaS/FaaS + Layered or Microkernel. Large team w/ platform eng → Microservices/SOA + IaaS/K8s.
2. **Domain complexity** → simple CRUD → Layered. Complex evolving business rules → DDD (+ Hexagonal to keep it testable).
3. **Load shape** → steady predictable → Layered/Client-Server. Bursty/event-driven → Serverless/Event-Driven. Extreme concurrency spikes → Space-Based.
4. **Compliance/vendor constraints** → existing Microsoft/enterprise contracts → Azure. AI-cost-sensitive/data-analytics-heavy → GCP. No strong pull → AWS default.

This project's own stack (`docs/ARCHITECTURE.md`) is: Layered core + Microkernel pack system + Hexagonal-ish boundary (LiteLLM adapter) + local-first/hybrid-cloud deployment — a worked example this heuristic already validates against.

## Suggested next step (not started)

Turn this into a **pack** (`packs/registry/architecture-advisor/`, kind: `intelligence`) that takes project context (team size, domain, load profile, compliance constraints — via a spec-engine intake once Phase 5 exists) and returns a ranked pattern + cloud recommendation with rationale, reusing this table as its knowledge base. Logged in `docs/BACKLOG.md`.
