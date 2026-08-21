# PromptWise Agentic OS — Research Findings & Revised Direction (Aug 2026)

**Purpose:** Re-validate the v3 implementation plan against the *current* (August 2026) problem landscape for AI coding agents, identify what to build to solve those problems, integrate the PromptWise plugin as the intelligence/governance core, and lay out a **zero/near-zero-cost, open-source-first** path to start implementation now.

**Verdict up front:** The v3 plan's core bets — hybrid local/cloud routing, governed action layer, self-hosted memory, one Compose bundle — are still the *right* bets and align exactly with where the market pain is in 2026. But the research shows the plan under-weights four things that have become the dominant problems this year: **verification/quality loops, context engineering, agent security (MCP/prompt injection), and spec-driven workflows.** It also over-weights packaging (ISO/OVA/voice) for a zero-budget solo start. The recommendation is to re-sequence: build the *quality + governance + cost* brain first (pure software, $0), and defer the heavy distribution formats.

---

## Part 1 — The Current Problem Landscape (what's actually broken in Aug 2026)

### P1. Quality crisis: "almost right, but not quite" code at scale
- Trust in AI output accuracy has **fallen to ~29–33%** (down from 40% in 2024) even as adoption passed 84–91% of developers; ~46% actively distrust output.
- **66% of developers** cite "almost right, but not quite" code as their top frustration — code that compiles, looks plausible, and is subtly wrong.
- Ecosystem-wide quality signals are degrading: copy/paste code up 48% since 2021, refactoring collapsed from ~24% to under 10%, and large-scale studies find substantially more defects in AI-generated code in the wild.
- Root cause per practitioner analysis: **not model capability but harness configuration** — top models hit 87–89% on SWE-bench Verified yet only ~46% on SWE-bench Pro; the recurring failure modes are declaring victory too early, breaking existing tests, spec drift, over-engineering, duplicate code from not reading the codebase, and circular retry loops.

### P2. Security: AI code is insecure, and the agents themselves are attack surface
- **~45% of AI-generated code contains security vulnerabilities** (Veracode); security findings in production surged ~10x in six months.
- The agent stack itself is now the target: **MCP tool poisoning** (malicious tool metadata steering agents), prompt injection via fetched content, confused-deputy attacks, token pass-through, SSRF, and rogue dynamic tool registration. Mitigations converging on: pinned/hashed tool provenance, an "MCP register" mapping every tool to owner/permission/kill-switch, scoped tokens, full audit logging, and sandboxed execution.
- Agents executing destructive commands unprompted remains a top-9 failure mode; guardrails/approval hooks are the standard fix.

### P3. Cost: unbounded token billing
- Real spend in 2026: light users ~$36/mo API, daily professionals ~$178/mo, heavy automation **$500–$2,000/engineer/mo** — enough that Microsoft cut Claude Code licenses for cost. Better agents → more usage → no ceiling.
- Proven levers, all of which are *routing/harness* features, not model features: **prompt caching (~10x cheaper on repeated prefixes), model routing (80% of tasks can go to models 10–50x cheaper), context compaction (50–70% input shrink), batch APIs (50% off)**. A DeepSeek-class model does a bug fix for $0.05 vs $0.54 on a frontier model.
- Local models are now genuinely usable for the routine tier: qwen3-coder:30b (MoE, ~19GB, 256K ctx), devstral:24b (46.8% SWE-bench Verified), gpt-oss:20b on 16GB RAM, qwen2.5-coder:7b on 8GB. Caveat: local single-GPU models cluster ~40% on Aider polyglot vs 70%+ for datacenter models — so **local-first must be paired with confidence escalation**, exactly as v3 designed.

### P4. Context rot & memory: long-running agents degrade
- Four canonical failure modes now well documented: **context poisoning** (a hallucination becomes "ground truth"), **context distraction** (~200K tokens and instructions get crowded out), **context confusion** (too many exposed tools → wrong calls), **context clash** (contradictory sources).
- The 2026 playbook is **write / select / compress / isolate**: external scratchpads and memory stores, per-step retrieval, compaction with smaller models, and sub-agent isolation with narrow interfaces.
- Cross-session memory is still the weakest link in every mainstream tool; open-source options have matured (Mem0, Letta, Zep/Graphiti, Cognee, LangMem) and all self-host on the Qdrant/SQLite-class infra the v3 plan already includes.

### P5. Workflow: the industry moved to spec-driven development (SDD)
- The backlash against "vibe coding" produced SDD as the dominant 2026 methodology: **constitution → specify → clarify → plan → tasks → implement → analyze**, with human review gates, EARS-notation acceptance criteria, and specs validated by generated tests. Tools: GitHub Spec Kit (open source), AWS Kiro, cc-sdd for Claude Code, Cursor Plan Mode.
- The "spec-anchored" level (specs and code evolve together with automated enforcement) is the recommended sweet spot; it directly attacks P1's spec-drift and hallucination failure modes.

### P6. Ecosystem gaps (the opportunity)
Even the best open-source agents (OpenHands, OpenCode ~185k stars, Cline, Aider, Goose, Kilo, Tabby) leave three gaps unfilled — stated explicitly by OpenHands' own ecosystem review:
1. **No unified observability/governance across multiple agents** — teams run 2–3 different agents and can't see cost, actions, or quality in one place.
2. **No portable workflows** — switching agents means rebuilding your harness.
3. **Air-gapped/local-sovereign deployment is bolted on, not designed in** — most tools put governance (audit, access control) behind commercial tiers.

**This is precisely the position PromptWise + the Agentic OS can own: the open-source, agent-agnostic governance/routing/memory/verification layer that sits UNDER any coding agent.**

---

## Part 2 — Problem → Solution Map (what the application must do)

| # | 2026 Problem | Solution in our stack | PromptWise tool involved | Status vs v3 plan |
|---|---|---|---|---|
| 1 | "Almost right" code, victory declared early | **Verification Gate:** every agent task ends with an enforced verify step — run tests, lint, diff review, self-check against spec; block "done" until pass | new `verify_output` + `run_eval_harness` | **NEW — must add** |
| 2 | Spec drift, over-engineering, scope creep | **Spec-anchored workflow:** built-in SDD pipeline (specify → plan → tasks → implement → verify) with EARS acceptance criteria stored as artifacts; integrate/borrow GitHub Spec Kit patterns | `orchestrate_tasks` + skill packs (81 packs already cover SDLC roles) | **NEW — promote SDLC skill packs to a first-class SDD engine** |
| 3 | Hallucinated APIs, duplicate code | **Codebase context service:** repo indexing (tree-sitter + embeddings in Qdrant) feeding `rank_context`; project conventions file auto-generated and injected | `rank_context`, `query_memory` | Partial in v3 (Phase 3) — extend to code-aware indexing |
| 4 | Circular retry loops, lost context | **Failure ledger + compaction:** failed-approaches log persisted per task; write/select/compress/isolate context policy; compaction via local small model ($0) | `query_memory`, `summarize_thread` | Partial — make explicit |
| 5 | Unbounded cost | **Router + budgets:** local-first tiers, confidence escalation, prompt-cache planning, per-task/per-DAG budgets, $/completed-task metric | `route_request`, `set_budget_limit`, `cost_report` | ✅ Core of v3 — keep, this is validated |
| 6 | Insecure generated code | **Security scan gate:** Semgrep + Gitleaks + dependency audit run automatically on agent output before commit | `scan_security` (exists in plugin) wired into verify gate | **NEW wiring** |
| 7 | MCP tool poisoning / rogue tools | **Tool registry & provenance:** allowlist of MCP servers with pinned versions/hashes, scoped tokens, kill switch; every tool call audited | `check_policy`, `record_audit` | **NEW — add tool-provenance to policy layer** |
| 8 | Prompt injection via fetched content | Content from web/files marked untrusted in context assembly; policy denies action-triggering from untrusted spans; local-only routing for sensitive data | `check_policy`, privacy-forced routing | Partial (privacy forcing exists) — extend |
| 9 | Destructive actions unprompted | Governed shell/fs with JIT grants + undo ring buffer + sandbox-by-default execution (Docker; microVM later) | `check_policy`, `grant_jit_permission` | ✅ v3 Phase 2 — validated, add sandbox default |
| 10 | No cross-session memory | Self-hosted hybrid RAG (Qdrant + BM25 + RRF) + a Mem0-style extraction layer for facts/decisions | `query_memory` | ✅ v3 Phase 3 — validated; add fact-extraction layer |
| 11 | No unified observability across agents | **Agent-agnostic gateway:** any agent (Claude Code, Cline, Aider, OpenCode, Goose) connects via MCP/OpenAI-compatible proxy; one dashboard shows cost, actions, audit, quality across all of them | gateway + `insights_report`, `export_audit` | **Reframe of v3 gateway — this is the killer positioning** |

---

## Part 3 — Revised Product Definition

**One sentence:** *An open-source "control plane" for AI coding agents — plug in any agent and any model (local or cloud), and get routing that cuts cost 60%+, a verification gate that kills "almost-right" code, governed and audited system actions, persistent memory, and spec-driven workflows — all self-hosted, from a laptop to a company VPC.*

### Why this framing wins
- It does **not** compete head-on with OpenHands/Cline/Aider (mature, huge communities). It makes them better and interchangeable — the gap they all admit they have.
- Every 2026 pain point (quality, security, cost, memory, observability) is a *layer* problem, and PromptWise's existing verbs (`route_request`, `check_policy`, `record_audit`, `query_memory`, `orchestrate_tasks`, `scan_security`, skill packs) are already the vocabulary of that layer.
- The "OS" delivery formats from v3 become *deployment options of the control plane* rather than the product itself — dramatically less work up front.

### Architecture (delta from v3 — additions in bold)
```
Interfaces: Web Dashboard · CLI · MCP clients (any coding agent) · Voice (later)
            **OpenAI-compatible proxy endpoint (so ANY tool can route through us)**
──────────────────────────────────────────────────────────────
PromptWise Core: route_request · orchestrate_tasks · check_policy ·
  grant_jit_permission · record_audit · query_memory · rank_context
  **+ verify_output (test/lint/security/spec gate)**
  **+ spec engine (specify→plan→tasks→implement→verify, EARS criteria)**
  **+ tool registry (MCP allowlist, pinned hashes, kill switch)**
  **+ context policy (write/select/compress/isolate, compaction via local model)**
──────────────────────────────────────────────────────────────
Model layer: Ollama (lazy/LRU, HW profiler) · **LiteLLM-style unified provider API**
  · cloud escalation (Claude/DeepSeek/etc., all optional)
Action layer: FS/shell MCP servers, policy-gated, **sandboxed-by-default (Docker)**
Memory layer: Qdrant + SQLite + local embeddings · **fact-extraction (Mem0-style)**
  · **code index (tree-sitter chunking)** · **failure ledger**
──────────────────────────────────────────────────────────────
Delivery: Docker Compose (canonical, $0) → everything else later
```

### Model catalog refresh (Aug 2026)
Replace the v3 examples with current best-per-tier (all free, all Ollama-pullable):

| Tier | Model | Needs | Why |
|---|---|---|---|
| local-code (GPU 24GB+) | qwen3-coder:30b (MoE 3.3B active) | ~19GB | best quality/VRAM, 256K ctx |
| local-code (16GB) | gpt-oss:20b or devstral:24b-q4 | 14GB | 128K ctx / best SWE-bench local |
| local-code (8GB) | qwen2.5-coder:7b | 4.7GB | solid baseline |
| local-general | llama3.x-class 3B / qwen 1.5B | 1.5–3GB | chat, classification, compaction |
| embed | nomic-embed-text (or newer) | 0.5GB | RAG |
| cloud-cheap | DeepSeek-class API | $ | 10–50x cheaper escalation rung before frontier |
| cloud-frontier | Claude Sonnet/Opus | $$ | final escalation only |

The catalog-driven design in v3 means this is literally a YAML update — the mechanism is validated, keep it.

---

## Part 4 — Zero-Budget Open-Source Stack (final picks)

Everything below is free, self-hostable, and runs on the machine you already have. **Total infra cost: $0.** Optional spend is only cloud-API escalation, and even that can be $0 (local-only mode).

| Layer | Pick | License | Why over alternatives |
|---|---|---|---|
| Local inference | **Ollama** (llama.cpp under the hood) | MIT | ubiquitous, GPU auto, keep_alive/LRU fits Model Manager design |
| Provider abstraction | **LiteLLM** (or thin custom proxy) | MIT | 100+ providers behind one OpenAI-compatible API; budgets/keys built in — saves weeks vs building the proxy |
| Vector DB | **Qdrant** | Apache-2.0 | v3 choice validated; single binary, hybrid search |
| Structured store | **SQLite** | PD | zero-ops |
| Memory/fact layer | **Mem0 (OSS)** patterns or build-thin on Qdrant | Apache-2.0 | benchmarked leader among OSS memory layers; can vendor just the extraction prompt-flow to avoid a dependency |
| Code indexing | **tree-sitter** + Qdrant | MIT | language-aware chunking for the codebase context service |
| Verification gate | **pytest/jest runners + Semgrep + Gitleaks + Ruff/ESLint** | OSS | the entire "almost-right code" answer is orchestrating these |
| Spec engine | **GitHub Spec Kit** (borrow templates/flow) | MIT | de-facto OSS reference for SDD; wrap in `orchestrate_tasks` |
| Sandbox | **Docker containers** now; gVisor/Firecracker as P2 | Apache-2.0 | Docker is the right zero-budget default; microVMs when multi-tenant |
| Gateway/dashboard | **FastAPI + a lightweight web UI** (React/Svelte, or HTMX to stay tiny) | MIT | one service, serves API + dashboard |
| Agents to integrate first | **Claude Code (via plugin/MCP), Aider, Cline, OpenCode** | OSS | Aider's git-native audit trail pairs beautifully with `record_audit` |
| Remote access | **Tailscale (free tier) / plain WireGuard** | free/GPL | v3 choice validated |
| Voice (deferred) | whisper.cpp + Piper + openWakeWord | MIT/GPL | unchanged from v3, just later |
| CI (free) | **GitHub Actions free tier** | — | the install/profiler test matrix from v3 runs here at $0 |

Hardware note: your existing laptop is the only infra needed for v1. The HW-profiler design in v3 explicitly makes low-RAM machines first-class — develop on whatever you have; the 1.5B–7B tier plus cloud free-tiers/cheap DeepSeek covers development itself.

---

## Part 5 — Re-sequenced Phase Plan (zero-budget solo edition)

Principle: ship the highest-pain, lowest-cost layers first; every phase produces something usable standalone. Packaging (ISO/OVA/WSL tar) and voice move to the end — they cost time, not money, but they don't solve the 2026 problems.

**Phase 0 (Week 1) — Compose foundation** *(unchanged from v3, trimmed)*
ollama + qdrant + gateway(FastAPI) + LiteLLM in one `docker compose up`. HW profiler v1 writes `hardware_profile.yaml`. Skip Tailscale wizard for now (doc it instead).

**Phase 1 (Weeks 2–3) — Hybrid router + Model Manager** *(v3 Phase 1, validated — keep acceptance criteria)*
Catalog-driven selection with the Aug-2026 model refresh, RAM watchdog, privacy-forced local routing, prompt-cache planning, `cost_report` with $/completed-task. **This alone is a shippable, marketable tool: "cut your agent bill 60%."**

**Phase 2 (Weeks 4–5) — Verification Gate ("almost-right killer")** *(NEW — promoted above system control)*
`verify_output`: baseline-tests-at-start, run-tests-after, lint, Semgrep+Gitleaks scan, diff-vs-spec self-review by a second (cheap/local) model, block-until-pass. Failure ledger to break retry loops. Works with any agent via MCP.

**Phase 3 (Weeks 6–7) — Governed system control + tool registry** *(v3 Phase 2 + security additions)*
Policy-gated fs/shell (sandboxed by default), JIT grants, undo buffer, hash-chained audit, **MCP tool allowlist with pinned versions and kill switch**, untrusted-content marking.

**Phase 4 (Weeks 8–9) — Memory & code context** *(v3 Phase 3 + code indexing + fact extraction)*
Hybrid BM25+vector RRF, ingestion daemon, tree-sitter repo index, Mem0-style fact/decision extraction, PII exclusion from cloud-bound context, context policy (compaction via local model).

**Phase 5 (Weeks 10–11) — Spec-driven workflow engine** *(NEW)*
SDD pipeline on `orchestrate_tasks`: specify → clarify → plan → tasks → implement (any connected agent) → verify (Phase 2 gate). EARS acceptance criteria as artifacts. Skill packs as phase personas.

**Phase 6 (Weeks 12–13) — Dashboard** *(v3 Phase 4, now richer)*
Chat + routing/cost badges, model manager panel, audit/policy viewer, **cross-agent observability view** (the ecosystem gap), spec/task board, first-run wizard.

**Phase 7+ (later / as traction demands)** — Voice, multi-agent orchestration extras, Tailscale wizard, live USB ISO, OVA, WSL tar, Terraform/Helm/SSO. Nothing here is wasted — v3's designs stay on the shelf, correctly specified.

### Success metrics (updated)
Keep v3's table, add three: **verification-gate catch rate** (% of agent outputs blocked then fixed), **$/completed-task trend**, **escaped-defect rate** on gated vs ungated tasks. Drop USB-boot and Terraform metrics from v1 scoreboard.

---

## Part 6 — Immediate Next Steps (this week, $0)

1. **Repo scaffold:** monorepo with `compose/`, `gateway/`, `profiler/`, `catalog/model_catalog.yaml` (Aug-2026 models above), `policies/`.
2. **Stand up Phase 0** on your laptop: Ollama + Qdrant + LiteLLM + FastAPI gateway; verify a chat round-trip through the gateway hits a local model.
3. **Wire PromptWise plugin → gateway:** expose `route_request`/`cost_report` against the live LiteLLM cost data so the plugin's routing advice becomes *enforcement*, not just advice.
4. **Prototype the Verification Gate as a standalone MCP server** (tests+lint+Semgrep on a diff) and use it in your own daily Claude Code sessions immediately — you become user #1, and it's the most demo-able piece.
5. **Write the constitution/spec for the project itself** using the SDD flow (dogfood Phase 5's shape from day one).
6. Defer: ISO/OVA/WSL/voice/Tailscale-wizard/enterprise — documented, not built.

---

## Sources

**Problems & quality:** [Stack Overflow — bugs & incidents with AI agents](https://stackoverflow.blog/2026/01/28/are-bugs-and-incidents-inevitable-with-ai-coding-agents/) · [9 failure modes of AI coding agents](https://beginnersinai.org/why-ai-coding-agents-fail/) · [AI coding adoption statistics 2026](https://www.digitalapplied.com/blog/ai-coding-adoption-statistics-2026-50-data-points) · [AI code quality crisis 2026](https://tech-insider.org/ie/ai-code-quality-crisis-2026/) · [Survey of bugs in AI-generated code (arXiv)](https://arxiv.org/html/2512.05239v1) · [Debt behind the AI boom (arXiv)](https://arxiv.org/html/2603.28592v1)

**Security:** [MCP tool poisoning — ITECS](https://itecsonline.com/post/mcp-tool-poisoning-enterprise-ai-agent-security-2026) · [AI agent security risks 2026 — FutureAGI](https://futureagi.com/blog/ai-agent-security-risks/) · [MCP security enterprise guide](https://www.langprotect.com/blog/mcp-security-enterprise-guide) · [Agentic AI risks — Forcepoint](https://www.forcepoint.com/blog/insights/agentic-ai-security-risks)

**Cost:** [AI coding costs 2026 — Morph](https://www.morphllm.com/ai-coding-costs) · [Managing token costs](https://blog.exceeds.ai/ai-coding-token-costs-2026/) · [Reduce AI coding token cost](https://www.atlascloud.ai/blog/guides/reduce-ai-coding-token-cost)

**Context & memory:** [Context engineering 2026 — four failure modes](https://www.reactify-solutions.com/articles/context-engineering-ai-agents-2026) · [Compaction vs context rot](https://medium.com/@pankaj_pandey/compaction-how-long-running-agents-beat-the-context-rot-problem-fc12d4cdeb7b) · [Mem0 vs Letta vs Zep](https://www.digitalapplied.com/blog/open-source-agent-memory-mem0-letta-zep-compared) · [Agent memory benchmarked 2026](https://rohitraj.tech/en/notes/open-source-ai-agent-memory-mem0-vs-zep-letta-2026)

**Spec-driven development:** [SDD in 2026 — DEV](https://dev.to/krlz/spec-driven-development-in-2026-what-it-is-the-tooling-and-how-teams-actually-use-it-2fk2) · [Best SDD tools — Augment](https://www.augmentcode.com/tools/best-spec-driven-development-tools)

**Open-source ecosystem:** [Top self-hosted coding agents — OpenHands](https://www.openhands.dev/blog/open-source-ai-coding-agents) · [9 open-source coding agents — SSOJet](https://ssojet.com/blog/open-source-ai-coding-agents) · [Best Ollama models Aug 2026 — Morph](https://www.morphllm.com/best-ollama-models) · [Best open-source coding LLMs — Pinggy](https://pinggy.io/blog/best_open_source_self_hosted_llms_for_coding/) · [AI agent sandboxing compared — amux](https://amux.io/guides/ai-agent-sandboxing/) · [E2B alternatives — Beam](https://www.beam.cloud/blog/best-e2b-alternatives)

---

# Part 7 — SDLC-Wide Coding Intelligence Modules (appended Aug 21, 2026)

**Scope of this addendum:** research on extending the platform beyond the control plane into full-lifecycle "coding intelligence" — multi-stack development, legacy migration, cloud/CI-CD, databases, design patterns & architecture, requirements-to-deployment workflows, documentation — usable by **both technical and non-technical people**.

## 7.1 What the research says, domain by domain

### A. Legacy modernization & migration (huge, underserved, agent-shaped)
- Microsoft's COBOL Agentic Migration Factory shows the working pattern: a **planner agent orchestrating specialist agents** (analyzer → dependency mapper → converter → test generator), with three phases: *prepare/enrich* (reverse-engineer business logic, clean/translate code), *analyze/map* (structure + dependency graphs), *transform/validate* (generate target code + test suites + migration reports).
- What breaks it: **context overload** (large windows → hallucination) and **call-chain complexity beyond ~3 levels**. What fixes it: Graph-RAG over the codebase, structure-aligned chunking, short controlled contexts, and treating deterministic artifacts (tests, call graphs) as orchestration aids — all capabilities our memory/code-index layer (Part 3) already plans. AWS (Transform), IBM, and Anthropic are all racing here — but there is **no open-source, self-hosted migration factory**. That's our lane.
- Key insight: migration is an *orchestration + governance* problem more than a translation problem — a per-node-tier DAG with verification gates, i.e., exactly `orchestrate_tasks` + the Phase 2 verify gate.

### B. Databases & data intelligence
- Text-to-SQL is mature enough for real use but enterprise-grade accuracy requires **schema-aware retrieval, query validation/dry-run, and semantic layers** — not raw prompting. Agentic patterns (generate → explain-plan → self-correct → execute read-only) are the 2026 standard.
- Practical modules that ride on our stack: schema understanding & documentation, migration script generation with rollback plans, query optimization (EXPLAIN-driven), test-data generation, and **governed** DB access (read-only by default, JIT grants for DDL/DML — our `check_policy` verbatim).

### C. Cloud, IaC & CI/CD
- Only **~55% of AI-generated IaC is secure by default**; identity/access config is the weakest area and maps directly to real breach patterns (multi-cloud breaches average $5.05M / 276 days to contain). The 2026 fixes are **policy-as-code validated *before* generation** (45% fewer violations), **agents as first-class RBAC actors** (junior-engineer-level permissions), drift detection with auto-remediation, and compliance-by-construction.
- AI velocity is breaking pipelines: code ships ~10x faster than CI/CD was designed for; the emerging answer is a **dual deployment model** — prompt-to-deploy for ephemeral preview environments, git-push-to-deploy for production, both under identical policy/audit. Our governance layer is the natural home for that shared policy plane.

### D. Requirements, documentation & the full lifecycle
- AI requirements tools now auto-draft BRDs/user stories/acceptance criteria from conversations and meetings, and flag ambiguity/conflicts; documentation trend is "docs as a by-product" — generated and kept in sync from code, specs, and audit trails rather than written after the fact.
- This is nearly free for us: the SDD engine (Part 5, Phase 5) already produces specs, plans, tasks, and EARS criteria as artifacts; the audit trail records what was actually built. **Documentation becomes a rendering of artifacts we already store** — README, architecture docs, ADRs, runbooks, user guides, release notes, compliance evidence.

### E. Non-technical users (the demand is proven, the safety isn't)
- **63% of vibe-coding users now have no coding background**; Gartner forecasts 60% of new code AI-generated by end of 2026. But 40–62% of AI code has vulnerabilities, **91.5% of vibe-coded apps had at least one hallucination-related flaw** in Q1 2026, and real breaches follow (Moltbook: 1.5M API keys exposed in 3 days from a missing row-level-security config). Stanford: AI-assisted users write *less* secure code while feeling *more* confident.
- The documented safe/unsafe boundary: personal tools, prototypes, internal utilities = fine; anything with auth, payments, health/finance data = needs engineering review. **Nobody enforces this boundary in software today.** A platform whose verification gate, security scans, and policy engine run *automatically* under a non-technical UI is the missing product: "vibe coding with a seatbelt."

## 7.2 Proposed module architecture: Intelligence Packs on the control plane

Everything above lands as **content + orchestration on the existing core** — not new infrastructure. PromptWise's 81 skill packs already prove the mechanism; we extend it into versioned, installable **Intelligence Packs**:

| Pack family | Contents | Rides on |
|---|---|---|
| **Stack packs** (Python/FastAPI, JS/TS/React/Node, Java/Spring, .NET, Go, Rust, PHP, mobile Flutter/RN…) | conventions, idioms, lint/test/build toolchain configs, framework-specific verify rules, common pitfalls | verify gate + code index + router (per-stack model prefs) |
| **Architecture & patterns packs** | design-pattern advisor (recognize/recommend/refactor-to), architecture styles (monolith→modular→microservices, event-driven, CQRS, hexagonal), ADR generator, C4/Mermaid diagram generation, anti-pattern detection | spec engine + `rank_context` + docs renderer |
| **Legacy migration packs** | the CAMF pattern generalized: analyzer/dependency-mapper/converter/test-gen agent DAGs per source→target pair (COBOL→Java, VB6/.NET-old→.NET-new, PHP5→8, AngularJS→modern, Oracle→Postgres, monolith→services) with Graph-RAG code maps and migration reports | `orchestrate_tasks` + code index + verify gate |
| **Database packs** | schema doc & ERD generation, governed text-to-SQL (explain-plan self-check, read-only default), migration scripts + rollback, query optimization, seed/test data | action layer (`check_policy` on DB ops) + memory |
| **Cloud & DevOps packs** | IaC generation with **pre-generation policy validation**, CI/CD pipeline authoring (GitHub Actions/GitLab), dual-track deploy (ephemeral preview vs gated production), containerization, drift checks, cost estimation | policy engine + audit + sandbox |
| **Lifecycle packs** | requirements capture (interview-style Q&A → BRD/user stories/EARS criteria), estimation, test-strategy, release notes, runbooks, compliance evidence export | SDD engine + audit trail + docs renderer |

Pack format: a folder of YAML/Markdown (persona prompts, verify rules, catalog hints, DAG templates) — community-contributable, no code changes to the core. This is also the ecosystem/moat play: an open pack registry does for this platform what extensions did for VS Code.

## 7.3 Dual-audience design: one engine, two faces

The research boundary (7.1-E) dictates the design: **same pipeline, different interface + different defaults.**

- **Builder mode (non-technical):** conversational requirements capture ("what do you want to build?") → the SDD engine silently produces spec/plan/tasks → agents build in a sandboxed preview with prompt-to-deploy → verification gate + security scans run **automatically and non-optionally** → results explained in plain language ("I blocked a version because your login form could leak passwords — fixed it") → production/publish step requires passing all gates, with sensitive-data classes (payments, health, auth-at-scale) flagged for a technical review handoff. Plain-language audit: "what did the AI do and why" as a readable timeline.
- **Pro mode (technical):** everything Builder does, plus raw spec/diff/policy editing, CLI/MCP access from their own agent (Claude Code, Aider, Cline…), tier pinning, pipeline/DAG authoring, and org policy administration.
- **Shared spine:** identical specs, gates, audit, and memory — so a non-technical founder can start an app in Builder mode and hand the *same project* to a developer in Pro mode with full history intact. That handoff story is unique in the market.

## 7.4 Where this slots into the phase plan (minimal disruption)

No re-sequencing needed — the Part 5 phases *are* the prerequisite core. Additions:

- **Phase 5 (SDD engine)** gains the requirements-capture conversational front-end and the docs renderer (docs from artifacts) — small increments on what's already scoped.
- **Phase 6 (Dashboard)** ships with the Builder/Pro mode split from day one; Builder mode is mostly progressive disclosure over existing APIs.
- **New Phase 8 (Weeks 14–17) — Intelligence Packs v1:** pack format + loader, 3 stack packs (pick your own daily stacks first), 1 database pack, 1 cloud/CI-CD pack, architecture-advisor pack. Dogfood on your own projects.
- **New Phase 9 (as demand shows) — Migration Factory:** generalize the CAMF DAG on `orchestrate_tasks` with Graph-RAG code maps; start with one high-demand pair (e.g., legacy PHP or AngularJS, or Oracle→Postgres) rather than COBOL, which needs mainframe access to test. This is also the clearest **paid-services wedge** for a zero-budget founder: run migrations for clients using your own platform.
- Everything remains $0 infra: packs are text; Graph-RAG uses the existing Qdrant + a NetworkX/SQLite call graph (no Neo4j needed at small scale); CI stays on free tiers.

**Priority guidance given zero budget:** Packs (Phase 8) before Migration Factory (Phase 9); within packs, your own stacks first (immediate dogfood value), database + CI/CD packs second (highest measured pain: 55%-secure IaC, pipeline bottlenecks), architecture pack third. Builder mode should follow — not precede — a rock-solid verification gate, because its entire promise is "safe for non-engineers."

## 7.5 Addendum sources

**Legacy migration:** [Microsoft — AI agents for COBOL migration (CAMF)](https://devblogs.microsoft.com/all-things-azure/how-we-use-ai-agents-for-cobol-migration-and-mainframe-modernization/) · [IBM vs Anthropic on COBOL modernization](https://futurumgroup.com/insights/ibm-vs-anthropic-a-tale-of-the-cobol-modernization-tape/) · [AWS Transform — AI agents for legacy workloads](https://finance.yahoo.com/news/aws-transform-aims-ai-agents-070000038.html) · [AI COBOL modernization 2026](https://medium.com/@hashbyt/what-happens-when-ai-meets-legacy-cobol-systems-00dae11f51d3)

**Databases:** [Agentic AI and text-to-SQL — Red Hat](https://developers.redhat.com/articles/2026/06/16/evolution-agentic-ai-and-text-sql) · [Text-to-SQL tools 2026 — Bytebase](https://www.bytebase.com/blog/top-text-to-sql-query-tools/) · [AI SQL query optimization — Syncfusion](https://www.syncfusion.com/blogs/post/ai-sql-query-optimization-2026) · [Enterprise text-to-SQL agents — Towards AI](https://pub.towardsai.net/architecting-state-of-the-art-text-to-sql-agents-for-enterprise-complexity-629c5c5197b8)

**Cloud/IaC/CI-CD:** [AI agents writing infrastructure code — DevOps.com](https://devops.com/ai-agents-are-writing-your-infrastructure-code-is-anyone-governing-it/) · [AI DevOps breaking CI/CD — Qovery](https://www.qovery.com/blog/ai-devops-2026-cicd-pipeline-bottleneck) · [IaC in 2026: where AI fits](https://clankercloud.ai/blog/iac-ai) · [Terraform scaling problem — InfoWorld](https://www.infoworld.com/article/4154543/the-terraform-scaling-problem-when-infrastructure-as-code-becomes-infrastructure-as-complexity.html)

**Requirements & docs:** [GenAI reshaping requirements engineering — Kovair](https://www.kovair.com/blogs/how-generative-ai-is-reshaping-requirements-engineering-and-software-documentation/) · [AI requirements tools 2026 — ONES](https://ones.com/blog/solution-guide/ai-requirements-engineering-tools/) · [AI documentation trends — Document360](https://document360.com/blog/ai-documentation-trends/) · [Best AI documentation tools — GitBook](https://www.gitbook.com/blog/best-ai-documentation-tools)

**Non-technical builders:** [63% of vibe-coding users are non-developers; breaches follow — TechTimes](https://www.techtimes.com/articles/317077/20260524/vibe-coding-non-developers-63-users-now-have-no-coding-background-breaches-follow.htm) · [Vibe coding trends 2026 — Keyhole](https://keyholesoftware.com/vibe-coding-trends-2026/) · [Vibe coding governance gap — CSA](https://labs.cloudsecurityalliance.org/research/csa-research-note-vibe-coding-ai-governance-gap-20260602-csa/) · [AI citizen development — Glide](https://www.glideapps.com/blog/ai-citizen-development)
