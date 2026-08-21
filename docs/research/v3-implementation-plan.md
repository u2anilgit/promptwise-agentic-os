# PromptWise Agentic OS — Implementation Plan (v3)

**Goal:** Extend the PromptWise plugin into a full agentic assistant stack on open-source Linux, with hybrid local/cloud model routing, governed system control, self-hosted memory/RAG, voice, and multi-agent orchestration — at zero or near-zero software cost, runnable by anyone (USB, VM, WSL, Docker) and hostable by enterprises on any cloud.

**Approach:** One core stack, many delivery formats. The intelligence/governance layer stays PromptWise (`route_request`, `check_policy`, `record_audit`, `query_memory`, `orchestrate_tasks`). The runtime ships as a **Docker Compose bundle** as the canonical form, wrapped into a **live USB ISO**, **VM image (OVA)**, **WSL2 distro**, and **cloud templates** — all produced from the same build pipeline.

---

## Problem Statement

PromptWise today optimizes, routes, and governs prompts, but it cannot act on a machine, remember across sessions with real retrieval, speak/listen, or run cheap local models. Users who want an autonomous assistant must bolt on ungoverned third-party tools and pay cloud API costs for tasks a 1–14B local model handles fine. And even good stacks fail at the last mile: if setup requires Linux knowledge, most users never get past the README.

## Goals

1. **Cut cloud spend ≥60%** by routing simple/private tasks to a local Ollama tier (measured via `cost_report` before/after).
2. **All system actions governed:** 100% of file/shell/service operations pass through `check_policy` and land in the hash-chained audit trail.
3. **Persistent memory:** ≥80% top-3 retrieval hit rate on prior-session facts via self-hosted RAG (`run_eval_harness`).
4. **Hands-free operation:** voice round-trip under 4 seconds on CPU-only hardware.
5. **Zero-to-working in minutes on any platform:** boot USB → chatting in <5 min; `docker compose up` → working in <10 min; WSL import → working in <10 min. No manual model or hardware configuration ever.
6. **Enterprise-ready hosting:** the same stack deploys to any cloud VM or Kubernetes cluster with multi-user auth, SSO, and centralized audit.

## Non-Goals

- **Full custom distro / desktop environment** — we ship a *live ISO remaster* of Debian (a build script, not a maintained distro). No custom kernel, package repo, or desktop shell.
- **Native Windows/macOS services** — Windows is served via WSL2 + Docker Desktop; macOS via Docker Desktop (CPU models) or a Linux VM. No native ports.
- **Fine-tuning local models** — inference-only for v1.
- **Heavy agent frameworks (AutoGen, CrewAI, LangGraph)** — `orchestrate_tasks` already provides the DAG runner.
- **GPU passthrough inside VMs** — VirtualBox/VMware GPU passthrough is fragile; VM mode is CPU-only by design and clearly labeled. GPU users should install natively or use cloud GPU instances.

---

## System Architecture

```
┌──────────────────────────────────────────────────────────┐
│                      Interfaces                           │
│  Web Dashboard (browser) · CLI (promptwise) · Voice       │
│  MCP clients (Claude Code, Cursor, any MCP host)          │
│  Remote devices via Tailscale (phone/laptop → box)        │
├──────────────────────────────────────────────────────────┤
│               PromptWise Core (extended)                  │
│  route_request (+local tiers) · orchestrate_tasks (+tier  │
│  per node) · check_policy · grant_jit_permission ·        │
│  record_audit · query_memory (+vector) · rank_context     │
├──────────────┬──────────────┬────────────────────────────┤
│ Model layer  │ Action layer │ Memory layer                │
│ HW Profiler +│ MCP servers: │ Qdrant (vectors)            │
│ Model Manager│  filesystem  │ SQLite (structured)         │
│  (RAM/GPU/   │  shell       │ local embeddings (Ollama)   │
│   CPU aware, │  systemd     │ Ingestion daemon            │
│   runtime    │  (policy-    │  (files, chats, tasks)      │
│   watchdog)  │   gated)     │                             │
│ Ollama (lazy │              │                             │
│  load / LRU) │              │                             │
│ Claude API   │              │                             │
│  (escalation)│              │                             │
├──────────────┴──────────────┴────────────────────────────┤
│              Docker Compose service bundle                │
│  (ollama · qdrant · promptwise-mcp · ingest · gateway ·   │
│   dashboard · voice*)          *voice runs native on host │
├──────────────────────────────────────────────────────────┤
│  Delivery formats (same bundle, different wrappers):      │
│  Live USB ISO │ Installed OS │ VM (OVA/ISO) │ WSL2 │      │
│  Any Linux (compose) │ Cloud VM / Kubernetes              │
└──────────────────────────────────────────────────────────┘
```

**Data flow (typical request):** input arrives (dashboard / CLI / voice / MCP / remote) → `build_context_model` classifies intent, `rank_context` pulls memory → `route_request` asks the Model Manager which tiers are *currently loadable* and picks: `local-small` / `local-code` / `local-large` (GPU) / `haiku` / `sonnet` / `opus` → system actions gated by `check_policy` (+ JIT) → result, cost, and actions written to `record_audit`.

---

## Hardware & Base System — Dynamic Model Manager

No fixed hardware profiles. The stack ships a **Hardware Profiler + Dynamic Model Manager** that adapts model selection at install time *and continuously at runtime*. The same install works unchanged on a 4 GB edge box, a 16 GB laptop, a GPU workstation, or a cloud GPU instance.

### Hardware Profiler (runs at install + on boot + on demand)
Detects and writes `config/hardware_profile.yaml`:
- **RAM**: total + available (`/proc/meminfo`; inside containers, host `/proc` is mounted read-only and cgroup limits are respected)
- **CPU**: cores, AVX2/AVX512/NEON flags (decides llama.cpp build path and thread count)
- **GPU**: NVIDIA (`nvidia-smi` → VRAM, CUDA version), AMD (ROCm), Intel/Apple (Vulkan/SYCL), or none
- **Disk**: free space on the model volume
- **Environment**: bare metal / live-USB / VM / WSL2 / container / cloud — each adjusts defaults (e.g., live-USB caps model size to fit RAM-disk; VM forces CPU mode)
- **Thermals/power** (optional): laptop-on-battery flag throttles concurrency

### Catalog-driven selection
Models are never hardcoded. `config/model_catalog.yaml` lists candidates per role with their *requirements*; the manager picks the best entry that fits **current free** resources:

```yaml
# model_catalog.yaml (excerpt — fully user-editable)
- name: qwen2.5-coder:14b-q4   role: code      min_free_ram_gb: 12  gpu_pref: true
- name: qwen2.5-coder:7b-q4    role: code      min_free_ram_gb: 6
- name: llama3.2:3b            role: general   min_free_ram_gb: 3
- name: qwen2.5:1.5b           role: general   min_free_ram_gb: 1.5
- name: nomic-embed-text       role: embed     min_free_ram_gb: 0.5
- name: whisper-small          role: stt       min_free_ram_gb: 1.5
- name: whisper-tiny           role: stt       min_free_ram_gb: 0.5
```

Adding a model = one YAML line. Users can pin models per role, force CPU-only, or cap RAM; pins always win.

### Runtime dynamics (RAM watchdog)
- **Lazy load / LRU eviction:** models load into Ollama on first use and unload (`keep_alive`) after idle; the manager evicts least-recently-used models when a bigger one needs RAM.
- **Pre-flight RAM check:** before routing to a local model, the manager checks free memory; if the model won't fit, it evicts idle models or transparently falls back one catalog rung (14B → 7B → 3B → 1.5B) without dropping the request.
- **Pressure downshift:** if available RAM falls below a watermark (other apps running), the active model downshifts and shifts back up when pressure clears; every shift is noted in `insights_report`.
- **Concurrency budget:** Ollama parallelism derived from cores/RAM/battery, consumed by the Phase 5 DAG scheduler.
- **Router integration:** `route_request` sees only *currently loadable* tiers — `local-large` appears automatically on a GPU box; `local-code` disappears on a 4 GB device.

### NVIDIA GPU support (first-class)
- **Detection:** profiler reads `nvidia-smi` for VRAM, driver, and CUDA version.
- **Native installs:** installer offers to add the NVIDIA driver + CUDA runtime when a card is detected.
- **Docker:** installer adds the **NVIDIA Container Toolkit** and starts the Ollama container with `--gpus all`; without a GPU the same compose file runs CPU-only (no edits needed — the GPU stanza is conditional via a compose override).
- **Offload autotune:** GPU layer count computed from *free* VRAM at load time; partial offload means a 4 GB card still accelerates a 7B model.
- **Cloud GPUs:** the same toolkit path works on any cloud GPU instance (T4/L4/A10G etc.); the profiler treats it identically to a local card.
- AMD (ROCm) and Intel/Apple (Vulkan/Metal) are P1 best-effort via Ollama's existing backends.

---

## Deployment & Distribution — One Build, Five Formats

A single build pipeline (`build/` scripts) produces every format from the same Compose bundle, so they never drift.

| Format | Who it's for | How they get it | GPU |
|---|---|---|---|
| **Docker Compose bundle** (canonical) | Anyone already on Linux/macOS/Windows-Docker | `curl -fsSL get.promptwise.dev \| sh` or `docker compose up` | ✅ via NVIDIA toolkit |
| **Live USB ISO** | Try-before-install; non-technical users | Flash ISO with balenaEtcher/Rufus, boot from USB | ✅ (drivers included) |
| **Installed OS** | Dedicated box / daily driver | "Install" button on the live desktop (Calamares) | ✅ |
| **VM image (OVA + same ISO)** | Windows/macOS users; cautious testers | Import OVA into VirtualBox/VMware/UTM, or boot the ISO in any VM | ❌ CPU-only (labeled) |
| **WSL2 distro** | Windows developers | `wsl --import promptwise.tar` or Docker Desktop + compose | ✅ (WSL2 CUDA) |
| **Cloud templates** | Enterprises & teams | Terraform module / cloud-init / Helm chart | ✅ GPU instances |

### Live USB ISO (Try → Install)
- Base: **Debian Live** remaster via `live-build` — a build script we run, not a distro we maintain.
- Preloaded: Docker + the Compose bundle + a small starter model (~2 GB) so first boot works fully offline; larger models download on first use if a network exists.
- **Try mode:** boots to a minimal desktop that auto-opens the Web Dashboard. Runs entirely from RAM (8 GB+ recommended for the live session). Optional **persistence partition** created with one click keeps chats, models, and settings across reboots on the same stick.
- **Install mode:** Calamares installer icon on the desktop — pick a disk, done. Post-install first boot runs the Hardware Profiler and offers NVIDIA drivers if a card is present.
- The profiler's `environment: live-usb` flag caps model selection to what fits in the RAM-disk.

### VM path
- The same ISO boots in VirtualBox, VMware, UTM, and QEMU; we additionally publish a pre-imported **OVA** for one-click import.
- VM mode is auto-detected → CPU models only, dashboard shows a "running in VM — CPU mode" badge with a link explaining the native/GPU option.
- Recommended VM settings documented: 4 vCPU / 8 GB RAM / 40 GB disk / bridged or NAT with port 8080 forwarded.

### WSL2 path (Windows)
- Option A (simplest): Docker Desktop with WSL2 backend → the standard compose bundle. NVIDIA GPUs work through WSL2's CUDA support with zero extra config on recent drivers.
- Option B: a distributable `promptwise.tar` imported via `wsl --import` — the full stack inside its own WSL distro, dashboard reachable at `localhost:8080` from Windows browsers.
- Voice on WSL is P2 (audio passthrough is awkward); text/dashboard/CLI fully supported.

---

## User Experience — How People Actually Work With It

Design principle: **the terminal is optional.** Every daily task is doable from a browser; the CLI and MCP interfaces exist for power users and tool integration.

### First-run wizard (all formats)
On first boot/start, the dashboard walks through: (1) hardware summary from the profiler + which models were auto-selected, (2) optional Claude API key for the escalation tier (skippable — stack is fully functional local-only), (3) privacy defaults (what gets ingested into memory), (4) optional Tailscale join for remote access. Under 2 minutes, no terminal.

### Interfaces, by user type
- **Everyday user → Web Dashboard** (`http://localhost:8080` or `promptwise-box` on the tailnet): chat with routing badges (which tier answered, cost so far), memory search, task/DAG view, model manager panel (what's loaded, RAM/VRAM gauges, pin/override controls), policy & audit viewer, one-click updates (`compose pull` behind a button).
- **Power user → CLI**: `promptwise chat`, `promptwise run <pipeline>`, `promptwise models`, `promptwise audit` — same API the dashboard uses.
- **Developer → MCP**: Claude Code, Cursor, or any MCP host connects to the gateway and gets the governed filesystem/shell/memory tools.
- **Hands-free → Voice** (native installs): wake word → speak → spoken reply.
- **On the go → any browser on the tailnet**: the dashboard is responsive; a phone on Tailscale can chat with the home box securely with zero exposed ports.

### Platform cheat-sheet (what we tell users)
- **Windows:** easiest = Docker Desktop → compose. Developer = WSL2 import. Cautious = VirtualBox OVA. 
- **macOS:** Docker Desktop (CPU models) or UTM VM.
- **Linux:** one-line install script → compose, or native install for voice/GPU-max.
- **No computer changes at all:** flash the USB, boot, try; unplug and nothing on the machine is touched.

---

## Remote Access & Network Security

- **Tailscale/WireGuard (default, $0):** the wizard offers a one-click join; every device gets a stable private name (`promptwise-box.tailnet.ts.net`). No ports exposed to the internet — mandatory posture for a stack that executes shell commands.
- **mDNS** (`promptwise.local`) for LAN-only, **DDNS + Caddy with auth** only if public reachability is truly required.
- **Gateway auth:** all API/dashboard access requires a token (shown once in the wizard); remote callers carry lower default trust in `check_policy` — read-only unless holding a JIT grant.
- Dynamic host IPs become irrelevant: the stable identity is the tailnet name, not the IP.

---

## Enterprise Cloud Hosting

Same bundle, hosted centrally, shared by a team. Cloud-agnostic by construction — everything is containers.

### Deployment tiers
1. **Single VM (start here):** Terraform module + cloud-init that provisions one VM (AWS EC2 / GCP CE / Azure VM / Oracle / Hetzner / DigitalOcean), installs Docker + NVIDIA toolkit (if GPU instance), pulls the compose bundle, and restores config from object storage. A `g4dn.xlarge`-class GPU instance serves a small team on 7–14B models; CPU instances work for light use.
2. **Kubernetes (scale):** Helm chart with the same services; Ollama as a GPU node-pool Deployment with model volume on a PVC, Qdrant as a StatefulSet, gateway behind an Ingress. Horizontal scale = more Ollama replicas; the Model Manager becomes a scheduler-aware placement hint.
3. **Marketplace images (P2):** prebuilt AMI / Azure image / GCP image for one-click launch.

### Enterprise-specific requirements
- **Multi-user & SSO:** gateway gains OIDC/SAML login (Keycloak or the IdP the org already has); per-user sessions, memory namespaces, and budgets. Roles map onto `check_policy` (viewer / operator / admin).
- **Centralized governance:** org-level policy pack overrides user policy; hash-chained audit exported to the org's SIEM (syslog/S3); `export_audit` gains scheduled shipping.
- **Data residency & privacy:** all inference and memory stay inside the org's VPC; the privacy-forced local routing means PII never reaches external APIs even when the escalation tier is enabled. Cloud escalation can be disabled entirely by policy for air-gapped deployments.
- **Cost controls:** per-user and per-team budgets via `set_budget_limit`; `project_cost_report` rolls up cloud-API spend + an instance-cost estimate.
- **Backup/DR:** nightly snapshot of Qdrant + SQLite + config to object storage; restore path tested in CI.

### Acceptance criteria (enterprise)
- [ ] Given the Terraform module and a fresh AWS account, when applied, then a working stack with dashboard + auth is reachable in <20 minutes.
- [ ] Given an OIDC-authenticated viewer role, when a shell action is attempted, then it is denied by policy and audited.
- [ ] Given cloud escalation disabled by org policy, when a complex task arrives, then it resolves on the largest local tier and never calls an external API.
- [ ] Given a GPU node in k8s, when Ollama schedules, then it lands on the GPU pool and the profiler reports VRAM correctly.

---

## Phase Plan

### Phase 0 — Compose-First Foundation (Week 1)
Compose bundle (ollama, qdrant, promptwise-mcp, ingest, gateway, dashboard-shell), one-line installer script, NVIDIA toolkit auto-setup, hardware profiler v1, Tailscale wizard step. Native `install.sh` retained as the fallback for voice/edge.
- [ ] Given a clean Ubuntu/Debian machine with an NVIDIA card, when the install script runs, then the stack is up with GPU inference in <10 min with no manual steps.
- [ ] Given the same script on a 4 GB CPU-only box, when run, then the stack starts with small models and no errors.

### Phase 1 — Hybrid Router + Dynamic Model Manager (Weeks 1–2)
Local tiers in `route_request` (privacy-forced local, budget pressure, confidence escalation), catalog-driven selection, RAM watchdog with pre-flight check / LRU eviction / pressure downshift, GPU offload autotune, `compare_providers` with $0 local tier.
- [ ] Given the same install on a 4 GB, a 16 GB, and a GPU machine, when profiled, then each selects appropriate catalog models with zero manual config.
- [ ] Given RAM pressure crossing the watermark, when a request is in flight, then the model downshifts one rung without dropping the request.
- [ ] Given a prompt containing an API key, when routed, then the tier is forced local and audited as `privacy_forced: true`.
- [ ] Given a user-pinned model, when routing, then the pin overrides the profiler.

### Phase 2 — Governed System Control (Weeks 3–4)
Filesystem / shell / systemd MCP servers gated by `check_policy` + JIT grants; `system_policy.yaml`; undo ring buffer; remote-caller reduced trust.
- [ ] Given no JIT grant, when the agent tries `rm` outside the workspace, then it is blocked and audited.
- [ ] Given any executed shell command, when `export_audit` runs, then it appears in the hash-chained trace.

### Phase 3 — Self-Hosted Memory & RAG (Weeks 5–6)
Qdrant + local embeddings; ingestion daemon (sessions, watched folders, decisions/learnings); hybrid BM25+vector retrieval with RRF; PII chunks excluded from cloud-bound context; memory hygiene.
- [ ] Given a fact from last week's session, when asked today, then it appears in top-3 retrieval.
- [ ] Given a PII-flagged chunk, when cloud context is assembled, then it is excluded and the exclusion audited.

### Phase 4 — Web Dashboard & UX (Weeks 7–8) *(promoted from P2 — required for "user-friendly")*
Chat with tier/cost badges, model manager panel, memory search, policy/audit viewer, first-run wizard, one-click updates, responsive/mobile layout.
- [ ] Given a fresh boot, when a non-technical user follows only the wizard, then they complete a chat and a file search without touching a terminal.
- [ ] Given the model manager panel, when a user pins a model, then the pin takes effect on the next request.

### Phase 5 — Voice Assistant (Weeks 9–10)
whisper.cpp (small/tiny by profiler) + openWakeWord + Piper; native service talking to the containerized brain; spoken confirmation for destructive actions; <4 s round-trip.

### Phase 6 — Multi-Agent Orchestration (Weeks 11–12)
Per-node tier selection in `orchestrate_tasks`, skill packs as agent personas, parallel local execution sized by the concurrency budget, shared blackboard namespace, per-DAG budgets, canned pipelines (`research-and-brief`, `code-review-swarm`, `daily-digest`).

### Phase 7 — Packaging & Enterprise (Weeks 13–14)
`live-build` ISO with Try/Install (Calamares) + persistence; OVA export; WSL2 tar; Terraform module + cloud-init; Helm chart; OIDC/SSO on the gateway; audit shipping; backup/restore.
- [ ] Given the ISO on a USB stick, when booted on a random laptop, then the dashboard opens and a local chat works with no network, in <5 minutes.
- [ ] Given "Install" on the live desktop, when completed, then the installed system boots to the same working stack and offers NVIDIA drivers if applicable.
- [ ] Given the OVA in VirtualBox, when imported with recommended settings, then the stack runs CPU-only with the VM badge shown.
- [ ] Given the WSL tar on Windows 11 with an NVIDIA GPU, when imported, then GPU inference works via WSL2 CUDA.

---

## Requirements Summary (MoSCoW)

**Must (P0):** Compose bundle + installer with NVIDIA auto-setup; dynamic model manager with runtime RAM watchdog; local routing with privacy forcing; governed filesystem/shell control; hybrid retrieval; web dashboard with wizard.
**Should (P1):** Live USB ISO with Try/Install; WSL2 path; voice pipeline; Tailscale wizard; per-node DAG tiering; Terraform single-VM enterprise deploy; AMD/Intel GPU best-effort.
**Could (P2):** OVA pre-built image; Helm chart; SSO/OIDC; cloud marketplace images; voice-on-WSL; wake word customization; canned pipelines.
**Won't (v1):** custom maintained distro; native Windows/macOS services; VM GPU passthrough; model fine-tuning; external agent frameworks.

## Success Metrics

| Metric | Target | Measured by |
|---|---|---|
| Cloud spend reduction | ≥60% vs baseline month | `cost_report` |
| Local-tier resolution rate | ≥60% of requests, quality-gate PASS | `insights_report` |
| Governed action coverage | 100% of system ops audited | `export_audit` sampling |
| Retrieval hit rate | ≥80% top-3 | `run_eval_harness` |
| Voice round-trip | <4 s | pipeline timing logs |
| USB boot → first chat | <5 min, zero terminal | live ISO test matrix |
| Compose/WSL install → working | <10 min | install CI on 4 GB / 16 GB / GPU runners |
| Enterprise Terraform → reachable stack | <20 min | deploy CI |
| Adaptation correctness | same artifact picks right models on 4 GB / 16 GB / GPU / VM / live-USB | profiler test matrix |

## Open Questions

- **[You/product]** Live ISO desktop: absolute-minimal (Openbox + browser kiosk) vs a light familiar desktop (XFCE)? Kiosk is smaller and simpler; XFCE feels more "real OS" for Install mode. (Non-blocking until Phase 7.)
- **[You/privacy]** Conversation ingestion into memory: opt-in per project or on-by-default with exclusions?
- **[Engineering]** WSL distribution: Docker-Desktop-only (less work) or also the standalone `wsl --import` tar? (Recommend both; tar is cheap once compose exists.)
- **[Engineering]** Enterprise k8s in v1 scope or defer Helm to v1.1 and ship Terraform-VM only? (Recommend defer; single VM covers most teams.)
- **[You/policy]** Default shell posture: JIT-per-class (recommended) or always-ask for anything mutating?

## Timeline & Dependencies

- **~14 weeks total**, phases independently shippable. 
- Dependency chain: Phase 0 → everything; Phase 1 → all routing-dependent phases; Phase 3 → Phase 6 blackboard; Phase 4 (dashboard) can start in parallel from Week 5; Phase 7 packaging depends only on Phase 0's bundle being stable, so ISO/WSL prototyping can begin early and harden at the end.
- Everything is $0 open-source software; the only spend is optional Claude API escalation and, for enterprises, their own cloud instances.
