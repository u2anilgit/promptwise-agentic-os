# Backlog

Tracks work that's been identified but deliberately deferred — findings from code review, follow-up items from a plan's final review, and known gaps against the spec/architecture docs. Not a duplicate of `docs/ROADMAP.md` (phase sequencing) — this is the finer-grained "known issues + quick wins" list that lives between phases.

Each entry: what, why it matters, where it came from, status.

## Open

### From `pack-loader-foundation` plan (merged `aa9cf4a`, 2026-08-24)

Final whole-branch review findings not fixed before merge (see `docs/superpowers/plans/2026-08-24-pack-loader-foundation.md` and the design spec it implements, `docs/superpowers/specs/2026-08-24-repo-intelligence-methodology-packs-design.md`).

- [ ] **Symlink handling unconsidered** — `list_installed_packs` uses `p.is_dir()` (follows symlinks, so a symlinked dir counts as an installed pack); `remove_pack`'s `shutil.rmtree` on a symlinked `packs/installed/<name>` raises rather than reporting cleanly. *Not yet fixed — lowest-priority item, deliberately left for a future pass.*
- [ ] **`dependencies` parsed but never resolved, `check_policy` capability registration not built** — both explicitly out of scope per the pack-loader-foundation spec, deferred to Phase 3. `install_pack` will happily install a pack whose declared deps are absent. `ARCHITECTURE.md` §3 now carries a status note flagging this as open (fixed 2026-08-24).

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
- [x] `_registry_dir()` bypassed config resolution — now resolves `paths.packs_registry` via `resolve_path`, same as `_installed_dir()`.
- [x] `version` field unvalidated — `PackManifest` now validates it via `parse_version`.
- [x] Stale/wrong import-cycle comment in `core/diagnostics/checks.py` — corrected.
- [x] Duplicate zero-packs doctor test — removed.
- [x] Unused `_config(root)` test parameter — dropped, call sites updated.
- [x] Near-tautological `test_defaults_to_running_core_version` — now patches to a distinctive version.
- [x] Untested reinstall-over-existing branch — covered.
- [x] Reinstall non-atomic — `install_pack` now copies to a temp dir and swaps into place; a failed reinstall no longer deletes the existing install first.

All merged via `chore/pack-loader-cleanup`, 2026-08-24.
