# Backlog

Tracks work that's been identified but deliberately deferred — findings from code review, follow-up items from a plan's final review, and known gaps against the spec/architecture docs. Not a duplicate of `docs/ROADMAP.md` (phase sequencing) — this is the finer-grained "known issues + quick wins" list that lives between phases.

Each entry: what, why it matters, where it came from, status.

## Open

### From `pack-loader-foundation` plan (merged `aa9cf4a`, 2026-08-24)

Final whole-branch review findings not fixed before merge (see `docs/superpowers/plans/2026-08-24-pack-loader-foundation.md` and the design spec it implements, `docs/superpowers/specs/2026-08-24-repo-intelligence-methodology-packs-design.md`).

- [ ] **`_registry_dir()` bypasses config resolution** (`core/packs/registry.py`) — hardcodes `root/packs/registry` instead of going through `resolve_path`/config like `_installed_dir()` does. No `paths.packs_registry` key exists in `core/config/defaults.yaml`. Consequence: `promptwise pack install` only works when cwd is the repo root — breaks under Docker Compose with an arbitrary workdir and the Phase 6.5 Tauri desktop track (no repo at all). *Important — real bug for non-repo-root deployments, not yet a blocker since nothing deploys that way today.*
- [ ] **`version` field unvalidated** (`core/packs/models.py`) — `PackManifest.version` is a free string even though `core/packs/semver.py`'s `parse_version` sits one module away. `requires_core` is validated strictly; a pack's own `version` is not. A `field_validator` calling `parse_version` closes this.
- [ ] **Stale/wrong comment in `core/diagnostics/checks.py`** — a comment near `_check_packs_integrity`'s local import claims it avoids a "diagnostics→packs→config import cycle"; no such cycle exists in the current import graph. Either correct the comment or promote the import to module level.
- [ ] **Duplicate test** in `core/tests/diagnostics/test_checks.py` — `test_packs_integrity_passes_with_zero_packs_direct` and `test_packs_integrity_passes_when_directory_does_not_exist` assert the same thing (missing dir → PASS/"0 packs"). Artifact of a rename during the fix loop; drop one.
- [ ] **Unused test parameter** — `_config(root)` helper in `core/tests/packs/test_registry.py` takes and ignores `root`; every call site passes `tmp_path` for nothing. Misleading (reads as tmp-scoped when it isn't).
- [ ] **Near-tautological test** — `test_defaults_to_running_core_version` in `core/tests/packs/test_loader.py` monkeypatches `core.__version__` to `"0.1.0"`, which is already its value. Patch to something distinctive (e.g. `"0.1.5"`) so the test would actually fail if the default stopped reading `core.__version__`.
- [ ] **Untested reinstall-over-existing branch** — `install_pack`'s `if dest_dir.exists(): shutil.rmtree(dest_dir)` path (the only destructive branch in the registry module) has no test.
- [ ] **Reinstall is non-atomic** — `rmtree` then `copytree` in `install_pack` means a failure between the two leaves the pack directory gone entirely, and silently discards any local edits under `packs/installed/<name>/`. Consider copy-to-temp-then-swap, or at minimum document the behavior.
- [ ] **Symlink handling unconsidered** — `list_installed_packs` uses `p.is_dir()` (follows symlinks, so a symlinked dir counts as an installed pack); `remove_pack`'s `shutil.rmtree` on a symlinked `packs/installed/<name>` raises rather than reporting cleanly.
- [ ] **`dependencies` parsed but never resolved** — `ARCHITECTURE.md` §3 promises the loader "resolves `dependencies`, and registers the pack's capabilities with `check_policy`"; neither is built yet (both explicitly out of scope per the pack-loader-foundation spec, deferred to Phases 3/8). `install_pack` will happily install a pack whose declared deps are absent. The loader's docstring says so; the architecture doc doesn't yet flag this as still-open — worth one clarifying line there.

### Repo-intelligence / methodology packs (blocked, tracked here so it isn't lost)

From `docs/superpowers/specs/2026-08-24-repo-intelligence-methodology-packs-design.md` — content blocked on Phases 3 (`check_policy`/`record_audit`), 4 (code index), 5 (spec engine/`orchestrate_tasks`), none of which exist in code yet.

- [ ] `repo-intelligence` pack (kind: intelligence) — feature/requirements/architecture/pseudocode/design extraction DAG.
- [ ] `bmad-methodology` pack (kind: lifecycle) — Business-model→Architecture→Design→Development DAG.
- [ ] `dmaic-methodology` pack (kind: lifecycle) — Define-Measure-Analyze-Improve-Control DAG.
- [ ] Open questions for whichever plan picks these up: complexity-threshold default for pseudocode extraction (config-tunable?); whether `extract-requirements`' EARS inference reuses Phase 5's spec-engine logic as a shared helper or reimplements it; golden-fixture repo size for the test suite.

### Phase-level (from `docs/ROADMAP.md`)

- [ ] **Phase 2 (Verification Gate)** — `core/verify/` (gate/ledger/runners/security) already has substantial code, but has not been confirmed against `ROADMAP.md`'s acceptance criteria (blocks a deliberately-broken diff, Semgrep/Gitleaks wired in, failure ledger breaks a retry loop after N identical failures, works against a real Claude Code session via MCP). No unbuilt dependency — this is the natural next phase-level work.
- [ ] **Phase 3 (Governed system control)** — `check_policy`, `record_audit`, JIT grants, audit hash-chain. Not started. Blocks Phase 4/5/8 content.
- [ ] **Phase 4 (Memory & code context)** — hybrid BM25+vector retrieval, tree-sitter code index. Not started.
- [ ] **Phase 5 (Spec-driven workflow engine)** — `specify/plan/tasks/implement/verify`. Not started.

## Resolved

- [x] Pack-loader foundation itself (schema/loader/registry/CLI/doctor wiring, `intelligence` pack kind) — `docs/superpowers/plans/2026-08-24-pack-loader-foundation.md`, merged `aa9cf4a` 2026-08-24.
