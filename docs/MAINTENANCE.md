# Maintenance, Support & Troubleshooting Mechanism

New module (not in the original v3 plan or the Aug-2026 findings doc — added per project direction: "this OS should have mechanism for maintenance and support, troubleshooting"). Ships from Phase 0, grows through later phases. Owned as a first-class core module, `core/diagnostics/`, alongside routing/policy/memory/verify.

## 1. Goals

- An org (or a solo user) can self-diagnose and self-heal the majority of problems without filing a ticket.
- When they do need help, they can produce a complete, redacted, shareable bundle in one command.
- Upgrades are safe by default: dry-run, versioned, reversible.
- Packs carry their own troubleshooting knowledge; the mechanism is generic, the content is distributed (same CMS pattern as §3 of `ARCHITECTURE.md`).

## 2. `promptwise doctor` — health checks

CLI + core verb `run_diagnostics()`. Runs a fixed set of core checks, then discovers and runs every installed pack's `troubleshooting.md`-declared checks. Each check returns `PASS / WARN / FAIL` with a one-line fix hint — never a bare boolean.

**Core checks (Phase 0 baseline):**

| Check | What it verifies | Failure hint example |
|---|---|---|
| `services.gateway` | FastAPI gateway responds on configured port | "gateway not listening on :8000 — is `docker compose up` running?" |
| `services.ollama` | Ollama reachable, at least one model pulled | "no models pulled — run `ollama pull qwen2.5-coder:7b`" |
| `services.qdrant` | Qdrant reachable, collections initialized | "Qdrant up but collections missing — run `promptwise memory init`" |
| `hardware.ram` | available RAM vs smallest configured model tier | "8GB free, local-code tier needs 14GB — falling back to local-small" |
| `config.resolve` | config layers (§4 of ARCHITECTURE.md) parse and merge without conflict | shows the exact file + key that conflicts |
| `policy.load` | all policy-as-code files in `policies/` + installed packs parse | shows the file + line that fails to parse |
| `packs.integrity` | every installed pack's `pack.yaml` validates, `requires_core` range satisfied | names the pack and the failing constraint |
| `audit.chain` | hash chain of the audit log is unbroken | flags the first broken link, does not auto-repair |

Exit code is non-zero if any check is FAIL, so `promptwise doctor` is CI-safe (`compose/` bundle runs it as a healthcheck).

## 3. Support bundle

`promptwise support-bundle [--out path.zip]` → `generate_support_bundle()`. Collects:

- Last N days of structured logs (core, gateway, per-pack) — secrets/API keys pattern-redacted before write, never after.
- Current resolved config (all 5 layers merged, with the *source layer* annotated per key) — again redacted.
- Recent audit trail entries relevant to the failure window.
- `promptwise doctor` output at bundle time.
- Installed pack list + versions + `requires_core` constraints.

Redaction is a shared utility (`core/diagnostics/redact.py`) used by both the bundle and any log-viewing dashboard panel — one implementation, not two.

## 4. Troubleshooting knowledge base

- **Core KB**: `docs/troubleshooting/` — one markdown file per known-issue class (routing, policy, memory, verify-gate, packs, upgrade). Referenced by doctor's failure hints (each hint links a KB anchor).
- **Pack KB**: each pack's own `troubleshooting.md` — pack authors document their own failure modes; the doctor loader concatenates these into the same searchable index at runtime. This is why the KB scales with the pack ecosystem without core maintainers writing every entry.
- Dashboard ships a "Diagnostics" panel (Phase 6) that renders doctor output + linked KB entries + a "generate support bundle" button — the non-technical-user-facing side of this mechanism (Builder mode, per the Aug-2026 findings §7.3).

## 5. Upgrade & rollback

- Core and every pack are independently semver-versioned (`ARCHITECTURE.md` §3).
- `promptwise upgrade --dry-run` shows: core version delta, pending Alembic migrations, packs whose `requires_core` would break, config keys that changed meaning (deprecation list).
- Real upgrade path: Alembic migration for SQLite/Postgres schema, Qdrant collection migration script if vector schema changed, compose image tag bump.
- Rollback: compose pins the previous image tag; SQLite/Qdrant restored from the pre-upgrade snapshot `promptwise upgrade` takes automatically before migrating. No upgrade proceeds without a snapshot succeeding first.
- Deprecation policy: a config key or verb signature change ships one minor version with a WARN in `doctor` before removal in the next major.

## 6. Support tiers (OSS default)

- **Community**: GitHub Issues/Discussions is the default and only tier for v1 — no infra cost, matches the $0 budget principle.
- Every issue template asks for the `support-bundle` output first — reduces back-and-forth, is the whole point of §3.
- A commercial/hosted support tier is explicitly a *later* business decision, not a v1 engineering task — do not build ticketing/SLA infra now.

## 7. Where this lands in the phase plan

Baseline (`doctor`, redaction, core KB skeleton) ships in **Phase 0** alongside the compose foundation — see `docs/superpowers/plans/2026-08-21-phase0-compose-foundation.md`. Support bundle + upgrade/rollback land in **Phase 3** (governed system control, same phase as audit hardening, since both depend on the hash-chained audit log). Dashboard Diagnostics panel lands in **Phase 6**. Per-pack troubleshooting KB entries are a requirement of the **Phase 8** pack-authoring guide, not optional polish.
