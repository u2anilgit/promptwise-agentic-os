# Architecture — Core Engine + Skill Pack System

Governs every design decision in `core/`, `gateway/`, and `packs/`. Read alongside `CLAUDE.md` goals 1–3 and 6 before adding any module.

## 1. Layering

```
Interfaces      Web dashboard · CLI · MCP clients (any agent) · OpenAI-compat proxy
Core Engine     route_request · orchestrate_tasks · check_policy · record_audit ·
                query_memory · rank_context · verify_output · spec engine ·
                tool registry · context policy · run_diagnostics (maintenance)
Model layer     Ollama (local) · LiteLLM (provider abstraction) · cloud escalation
Action layer    FS/shell/DB MCP servers, policy-gated, sandboxed by default
Memory layer    Qdrant + SQLite · fact extraction · code index · failure ledger
Pack layer      Installable modules carrying ALL domain knowledge (see §3)
Delivery        Docker Compose (server, canonical, Phase 0) · native desktop app
                (Linux software-center + Windows installer, Phase 6.5) · Debian
                live-ISO appliance (deferred, Phase 7+) — see §6
```

Core Engine and Model/Action/Memory layers are collectively "the engine" — generic, domain-agnostic, installed once. Packs are optional, composable, uninstallable without breaking the engine.

## 2. Core Engine verbs (the stable contract)

These are the only entry points a pack or external agent ever calls. Adding a verb is a core-engine decision (needs a plan); packs never invent new core verbs, only new *pack tools* that call existing verbs.

| Verb | Responsibility | Notes |
|---|---|---|
| `route_request(task, constraints)` | pick model tier (local-small/local-code/local-large/cloud-cheap/cloud-frontier) | catalog-driven, `catalog/model_catalog.yaml`, privacy-forced local routing |
| `orchestrate_tasks(dag)` | run a DAG of steps across agents/tools, per-node tier | backs both spec-engine pipelines and pack-provided DAG templates |
| `check_policy(action, context)` | allow/deny/require-JIT-grant for any fs/shell/DB/cloud action | policy-as-code in `policies/`, packs ship *additional* rule files, never bypass |
| `grant_jit_permission(scope, ttl)` | time-boxed elevated permission | undo-buffer-backed |
| `record_audit(event)` | append to hash-chained audit log | every action from every layer, no exceptions |
| `query_memory(query, scope)` | hybrid BM25+vector retrieval (RRF) | scope = session/project/org |
| `rank_context(candidates, task)` | context selection under a token budget | implements write/select/compress/isolate |
| `verify_output(diff, spec)` | tests + lint + Semgrep/Gitleaks + spec self-check, block until pass | the P1 fix — mandatory, see `CLAUDE.md` goal 3 |
| spec engine (`specify/plan/tasks/implement/verify`) | SDD pipeline, EARS acceptance criteria as artifacts | wraps `orchestrate_tasks` |
| tool registry | MCP allowlist, pinned versions/hashes, kill switch | closes the P2/P7 gap |
| `run_diagnostics()` / `generate_support_bundle()` | health checks, redacted log/config bundle | see `MAINTENANCE.md` |

## 3. Skill Packs (the CMS pattern)

A pack is a folder under `packs/registry/<pack-name>/` — pure content + declarative config, **no core code changes required to add, update, or remove one.**

### Pack contract

```
packs/registry/<pack-name>/
  pack.yaml              # manifest — required
  personas/               # role-flavored system prompts (e.g. reviewer, migrator)
  verify-rules/            # extra lint/test/security rules layered onto verify_output
  catalog-hints.yaml       # model-tier preferences for this pack's task types
  dags/                    # orchestrate_tasks DAG templates this pack contributes
  tools/                   # optional pack-scoped MCP tool definitions (declarative, policy-gated)
  troubleshooting.md       # pack-specific entries for `promptwise doctor` / support KB
  CHANGELOG.md
```

`pack.yaml` (required fields):

```yaml
name: stack-python-fastapi
version: 1.0.0
kind: stack            # stack | database | cloud-devops | architecture | migration | lifecycle | intelligence
summary: Python/FastAPI conventions, verify rules, and model-tier preferences
requires_core: ">=0.1.0,<0.2.0"
capabilities:            # declared least-privilege — enforced by check_policy at install AND runtime
  - fs:read
  - shell:run:pytest
  - shell:run:ruff
permissions_rationale: >
  Needs shell access only to invoke pytest/ruff during verify_output; no fs:write, no network.
dependencies: []          # other pack names this one requires
```

### Pack families (from `research/aug2026-findings.md` Part 7)

| Family | Carries | Rides on core verb |
|---|---|---|
| Stack packs | language/framework conventions, verify rules, pitfalls | `verify_output`, `rank_context`, `route_request` |
| Architecture packs | pattern advisor, ADR generator, diagram gen, anti-pattern detection | spec engine, `rank_context` |
| Legacy migration packs | analyzer/mapper/converter/test-gen DAGs per source→target pair | `orchestrate_tasks`, code index, `verify_output` |
| Database packs | schema docs, governed text-to-SQL, migration+rollback, query opt | `check_policy` (DB ops), memory |
| Cloud/DevOps packs | IaC gen with pre-gen policy validation, CI/CD authoring, drift checks | policy engine, audit, sandbox |
| Lifecycle packs | requirements capture, EARS criteria, release notes, runbooks | spec engine, audit trail |
| Intelligence packs | reverse-engineers an existing repo into feature/requirements/architecture/pseudocode/design docs | `orchestrate_tasks`, `rank_context`, code index |

### Install/discovery mechanism

1. `promptwise pack install <name>[@version]` copies (or symlinks in dev) `packs/registry/<name>/` into `packs/installed/<name>/`.
2. Core's pack loader validates `pack.yaml` against the manifest schema, checks `requires_core` semver range, resolves `dependencies`, and registers the pack's capabilities with `check_policy` **before** any pack content is exposed to an agent. *(Status: schema/semver validation and dependency-presence checking — `install_pack` refuses to install a pack whose declared dependencies aren't already installed — shipped. Not yet built: no version-constrained dependency resolution or auto-install-in-order, and no automatic `check_policy` capability registration for an installed pack's declared `capabilities` — that needs an actor-scoped policy model check_policy doesn't have yet. See `docs/BACKLOG.md`.)*
3. Packs are hot-discoverable — the loader watches `packs/installed/` and re-registers on change; no core restart required for content-only packs (persona/verify-rule/DAG changes). Adding a new *capability* to an already-installed pack requires an explicit re-approval (policy re-grant), never silent escalation.
4. `promptwise pack list / pack remove <name>` — removal deletes from `packs/installed/` and deregisters; core and other packs keep working.

### Why this satisfies "flexible, adaptable, customizable, configurable"

- **Flexible**: any domain becomes a pack; core never needs to know about it in advance.
- **Adaptable**: packs version independently of core (`requires_core` range) and of each other.
- **Customizable**: an org forks a pack, not the core, to tune conventions for its house style.
- **Configurable**: which packs are active, their capability grants, and their catalog hints are all config, not code (see §4).

## 4. Configuration layering

Single resolution order, later wins, all layers optional except system defaults:

```
1. System defaults        core/config/defaults.yaml            (ships with engine)
2. Org config             promptwise.config.yaml (repo root)   (org-wide: enabled packs, budgets, policy overrides)
3. Project config          .promptwise/config.yaml (per-project) (project-specific overrides)
4. User local overrides    .promptwise/local.yaml (gitignored)  (individual dev's local tweaks)
5. Environment variables   PROMPTWISE_*                          (deployment secrets, CI overrides — always wins)
```

Every core verb and every pack reads config through one resolver (`core/config/resolve.py`, Phase 0) — never reads a file directly. This is what makes "easily configurable" actually true instead of aspirational: one code path, one precedence order, fully documented.

## 5. Stack rationale (why these choices)

- **Python/FastAPI core**: matches every tool already validated in the research doc (LiteLLM, tree-sitter bindings, pytest/Semgrep/Gitleaks orchestration, Qdrant client) — one language across gateway, verify-gate, and MCP servers minimizes integration seams.
- **TypeScript/React dashboard**: the MCP ecosystem (Claude Code, Cursor, OpenCode) and most agent tooling is TS-first; the dashboard is also where "any agent" observability (P6/#11) needs to feel native to that ecosystem.
- **SQLite → Postgres from day one**: SQLAlchemy 2.0 models written Postgres-clean; SQLite is the $0-infra default, Postgres is a config change, not a rewrite, when an org scales past one box.
- **Docker sandbox default**: zero-budget-correct per the research doc; gVisor/Firecracker is a Phase 9+ multi-tenant concern, not a v1 one.

## 6. Delivery & packaging (three tracks, one core — updated)

Direction confirmed: ship as a **package**, not a distro, and reach users on their platform's own install path — Linux software centers, a Windows download-and-run installer — before considering a bootable appliance. All three tracks below run the *same* `core/` + `gateway/` + pack system; only the shell around it and the sidecar-vs-container choice for Ollama/Qdrant changes.

| Track | Who it's for | Install experience | Runtime |
|---|---|---|---|
| **Server** (Phase 0, canonical) | self-hosters, orgs, CI, cloud VPC | `docker compose up` | Ollama + Qdrant + gateway as containers |
| **Desktop** (Phase 6.5, new) | individual devs, non-technical Builder-mode users | Linux: Flathub/software-center + AppImage. Windows: signed `.exe`/`.msi` | Same gateway compiled to a native binary, Ollama + Qdrant as bundled sidecar binaries — **no Docker required** |
| **Appliance** (Phase 7+, deferred) | offline/kiosk/air-gapped boxes | flash a live-USB image | Debian remaster running the Server track's Compose bundle |

### Desktop track mechanics (Phase 6.5)

- **Shell:** Tauri (Rust) wrapping the same React dashboard built in Phase 6 — zero duplicated UI work, one codebase renders in both the browser (server track) and the native window (desktop track).
- **Backend sidecar:** the `gateway/` FastAPI app compiled to a standalone binary (PyInstaller or Nuitka) and launched by Tauri as a managed child process — starts on app launch, stops on quit, no separate service install step for the user.
- **Model/vector sidecars:** Ollama and Qdrant both ship single static binaries upstream — bundled the same way as the gateway sidecar, not run in containers. This is what removes the Docker dependency for desktop users entirely.
- **System integration:** tray icon, optional auto-start on login, local-only network binding by default (matches `CLAUDE.md` goal 5 — $0, offline-capable).
- **Packaging outputs from one Tauri build:**
  - Linux: Flatpak manifest → Flathub submission (the actual "software center" entry on GNOME Software/KDE Discover/most distro stores), plus AppImage for portable/no-store use, plus `.deb`/`.rpm` as a fallback for apt/dnf-only users.
  - Windows: Tauri's built-in NSIS/WiX bundler produces a signed `.msi`/`.exe`; winget manifest submission is a follow-on once the installer is stable (puts it in `winget install` too, the closest Windows equivalent of a software center).
  - macOS: same Tauri build produces a `.dmg`/`.app`; notarization follows once Windows/Linux ship — not a blocker for either.
- **Config/pack parity:** desktop track reads the exact same 5-layer config (§4) and installs packs into the same `packs/installed/` contract (§3) — a project can move between a desktop install and a server deployment with no format translation.

### Appliance track (Phase 7+, unchanged in spirit)

Debian live-build remaster that bakes the Server track's Compose bundle plus a first-run wizard onto a bootable image. Still not a maintained distro fork — no custom kernel, no custom package repo (`VISION.md` non-goals). Only reconsidered if the desktop/server tracks show demand for an offline-appliance form factor.

## 7. Boundaries enforced by review

- A PR that adds domain-specific logic (a specific language, a specific cloud provider, a specific framework) to `core/` or `gateway/` should be rejected — it belongs in a pack. This is the single most important architectural rule to enforce in code review.
- A PR that has a pack reach fs/shell/DB directly instead of through `check_policy` should be rejected.
