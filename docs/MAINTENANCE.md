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
| `deps.integrity` | no installed package is on `security/known_bad_packages.yaml` (FAIL); `requirements.lock` exists, is hash-pinned and matches installed versions (WARN) | "litellm==1.82.8 (malicious release) — uninstall and rotate credentials"; "no lockfile — generate with `uv pip compile --generate-hashes`" |

Exit code is non-zero if any check is FAIL, so `promptwise doctor` is CI-safe (`compose/` bundle runs it as a healthcheck).

## 2b. Dependency locking (supply chain)

`requirements.lock` (runtime) and `requirements-dev.lock` (runtime + dev) pin every package, including transitive ones, with sha256 hashes. They are universal for Python 3.12-3.13 (`requires-python = ">=3.12,<3.14"`). The image (`compose/gateway.Dockerfile`) and CI install only from them (`pip install --require-hashes -r requirements.lock`, `uv pip sync --require-hashes requirements-dev.lock`), so an unexpected or tampered wheel fails the install. `promptwise doctor` (`deps.integrity`) FAILs on a package listed in `security/known_bad_packages.yaml` and WARNs when the environment differs from the lock; fix a WARN with `uv pip sync --require-hashes requirements.lock`.

**Supported dev environment** (`pyproject.toml` requires Python 3.12-3.13; the machine default may be older): `uv venv .venv --python 3.12`, then `uv pip sync --require-hashes -p .venv/Scripts/python.exe requirements-dev.lock` and `uv pip install -p .venv/Scripts/python.exe --no-deps -e .` (use `.venv/bin/python` on Linux/macOS), and run everything with that interpreter. `promptwise doctor` reports `deps.integrity` PASS in it.

Regenerate (uv keeps existing pins as preferences, so only intended bumps change). The dev lock is compiled under the runtime lock's constraints (`-c requirements.lock`) so shared packages never differ (guarded by `test_dev_lock_is_a_superset_of_the_runtime_lock_with_identical_pins`):

```
uv pip compile pyproject.toml --universal --python-version 3.12 --generate-hashes --no-header -o requirements.lock
uv pip compile pyproject.toml --universal --python-version 3.12 --generate-hashes --no-header --extra dev -c requirements.lock -o requirements-dev.lock
# bump one package: add  --upgrade-package <name>
```

A lock is only trusted after it is exercised: create a venv from the dev lock (`uv venv --python 3.12`, `uv pip sync --require-hashes requirements-dev.lock`, `uv pip install --no-deps -e .`) and run the full suite in it. `core/tests/security/test_lockfiles.py` guards that every pin is hashed, none is on the known-bad list, every direct dependency is present, and LiteLLM is absent. Add a bad release to `security/known_bad_packages.yaml` the moment an advisory lands.

## 2b-1. Gateway API credential (operator reference)

The HTTP API (everything but `/healthz`) needs a bearer credential stored at `gateway.token_path` (default `~/.promptwise/dashboard_token`: the user's home, deliberately NOT the gateway's working directory, which may be a project an agent can edit; created on first use with mode 0600). `promptwise dashboard token` prints it. Rotate by replacing the file contents (read on every request, no restart). A file that is a symlink, unwritable, or shorter than 32 characters fails closed: every route returns 503 `credential unavailable` and the reason is logged. In the compose deployment `/app/.promptwise` is a read-only mount, so the default lands in the container's home and changes when the container is recreated; to keep one stable credential, mount a writable file and set `PROMPTWISE_GATEWAY__TOKEN_PATH` to it. The CLI prints the file for the environment it runs in, so run it inside the container (`docker compose exec gateway python -m scripts.promptwise dashboard token`) when the gateway runs there. Failed attempts appear in the audit log as `api_auth_denied` (rate-limited to one per second). Keep the gateway on loopback (compose binds `127.0.0.1` by default; do not set `BIND_ADDR=0.0.0.0` without a TLS reverse proxy: the credential travels in a header).

## 2b-2. Usage ledger (operator reference)

Agents report model usage with the `record_usage` MCP tool (or `promptwise usage record`); `promptwise usage report` and the dashboard Cost view read it back. It is **self-reported**: core calls no LLM and the gateway does not see model traffic, so under-reporting is possible and the UI says so. Cost is computed once from the catalog tier at record time and stored (editing prices later does not rewrite history); unknown tiers and out-of-range or non-integer token counts are rejected; every record is audited (`usage_recorded`). Storage is the `usage_event` table (migration 0004) in the gateway's pinned database.

## 2c. Independent verification (operator reference)

A task reaches `done` only after `complete_task` passes every layer below; `promptwise spec complete` and the MCP result report which independent layers backed the acceptance (`independence`).

| Layer | Always on? | What it proves | Config |
|---|---|---|---|
| Frozen check files | yes | the check was not edited after the plan | - |
| Grounded gate | yes (override: `spec.allow_ungrounded`) | a real test command ran | `verify.test_command` |
| **Red before green** | yes | every acceptance check ran properly (program found, no timeout) and FAILED on two consecutive runs before the work existed, writing nothing to the project tree; a check that already passes, is flaky or mutates the tree is rejected | per check: `expect_baseline` = `fail` (default) or `pass` (explicit regression guard); operator: `spec.allow_regression_guards` (default true; set false to forbid guards) |
| Mutation gate | opt-in | the tests detect injected faults | `verify.mutation_command` (exit 0 = the tool's own threshold met), `verify.mutation_timeout_seconds`, `spec.require_mutation` |
| Independent reviewer | opt-in | a second party (another model, agent or human) approves | `verify.reviewer_command`, `verify.reviewer_timeout_seconds`, `spec.require_reviewer` |

**Reviewer contract:** the command reads one JSON document on stdin — `{spec_id, task_id, requirements:[{id,text}], evidence, checks:[{requirement_id, command, baseline, passed}]}` — and prints `{"approved": true|false, "reasons": [str]}`. Anything else (non-zero exit, timeout, missing program, malformed JSON, non-boolean `approved`) is a rejection. Reasons are capped at 10 x 300 characters and are returned to the agent as untrusted data. Core never calls an LLM; wire the command to whatever model or process you trust.

**What "red" does and does not prove:** it proves the check can fail and was not self-modifying within the project tree. It cannot rule out a check that keeps state somewhere core cannot see (e.g. a temp file outside the tree that arms a later pass): that residual risk is what the mutation gate and the reviewer hook are for.

**Trust:** `mutation_command` and `reviewer_command` run with the gateway's privileges and its environment, so they are read only from operator config. Over MCP a project can never set them (only pre-approved `test_command`/`lint_command` strings are honoured) and cannot satisfy a required reviewer with its own command. On the **CLI** the project's own `.promptwise/` layers are the user's configuration, so these settings are enforceable against an agent only if that agent cannot write them (see the single-repo caveat in `gateway/CLAUDE.md`). The mutation and reviewer programs always run from the project root, never from an agent-chosen `cwd`; keep the programs and their config **outside** any directory the agent can write, because a script inside the project is agent-writable.

The reviewer receives each check's file path, sha256 and (truncated) source, `evidence_sha256`, and `evidence_untrusted: true` (the evidence is agent-written text: do not follow instructions in it). Approvals log the reviewer's reasons in the audit entry.

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
