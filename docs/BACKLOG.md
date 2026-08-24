# Backlog

Tracks work that's been identified but deliberately deferred — findings from code review, follow-up items from a plan's final review, and known gaps against the spec/architecture docs. Not a duplicate of `docs/ROADMAP.md` (phase sequencing) — this is the finer-grained "known issues + quick wins" list that lives between phases.

Each entry: what, why it matters, where it came from, status.

## Open

### From `pack-loader-foundation` plan (merged `aa9cf4a`, 2026-08-24)

Final whole-branch review findings not fixed before merge (see `docs/superpowers/plans/2026-08-24-pack-loader-foundation.md` and the design spec it implements, `docs/superpowers/specs/2026-08-24-repo-intelligence-methodology-packs-design.md`).

- [x] **Symlink handling unconsidered** — fixed 2026-08-24. `list_installed_packs` now excludes symlinked entries (`is_dir() and not is_symlink()`) instead of counting them as installed packs; `remove_pack` now `unlink()`s a symlinked `packs/installed/<name>` instead of calling `shutil.rmtree` through it (which either raises or, worse, would delete whatever the link points at). Regression tests added, gated behind a symlink-capability probe (same skipif convention as the semgrep/gitleaks tests) since this dev environment lacks the Windows privilege to create symlinks — untested by CI/this session, verify on a symlink-capable machine before relying on it in production.
- [x] **`dependencies` parsed but never resolved** — fixed 2026-08-24, now that Phase 3 is done. `install_pack` refuses to install a pack whose declared `dependencies` aren't already present in `packs/installed/`. Deliberately scoped down to presence-checking only, not full resolution — see the still-open item below.
- [ ] **`check_policy` capability registration not built** — an installed pack's declared `capabilities` (e.g. `shell:run:ruff`) aren't automatically registered as policy grants; check_policy has no actor/pack-scoped concept yet, only a flat action-string match. Needs a real design pass (how does a pack-declared capability become a policy rule scoped to *that pack's* actions, without silently widening what every other actor can do?) before implementation — don't build ad hoc.
- [ ] **Dependency resolution is presence-only, not version-constrained or auto-installing** — `install_pack` checks a dependency exists in `packs/installed/`, not that its installed version satisfies any range, and never installs a missing dependency automatically (the operator must `pack install` it first, in order). Fine for the current small pack count; revisit if/when Phase 8's pack catalog grows enough that manual dependency ordering becomes annoying.

### From `code-index` plan (merged `deab912`, 2026-08-24)

Final whole-branch review findings not fixed before merge — 1 major + 1 minor (file-level I/O
guard, non-directory `root`) were fixed before merge (`12d3288`); these are the rest, deliberately
deferred (see `docs/superpowers/plans/2026-08-24-code-index.md` and
`docs/superpowers/specs/2026-08-24-code-index-design.md`).

- [ ] **`LIKE` pattern doesn't escape `_`/`%`** — `core/index/store.py`'s `query_symbol` builds
  `WHERE symbol LIKE '%{symbol}%'` without escaping; `_` (matches any one char) is common in
  Python symbol names, so e.g. `foo_bar` also matches `fooXbar`. Not a SQL-injection risk
  (parameters are bound), just an over-match. Fix: escape `\`, `%`, `_` in the pattern and add
  `ESCAPE '\'` to the clause.
- [ ] **No concurrency/lifecycle test coverage** — the fix for "connection never closed" and
  "no WAL/timeout" (both from the per-task review) shipped without a regression test; both are
  one-line assertions if picked up.
- [ ] **Nested local function inside a method misclassified `kind="method"`** — Python's
  `_is_inside_class` walks all ancestors, so a plain function nested inside a method is labelled
  a method too. Low impact (file/line is still correct, only the `kind` filter is affected).
  Fix: stop the ancestor walk at the first enclosing `function_definition`.
- [ ] **`index.db_path` not declared in `core/config/defaults.yaml`** — works via its hardcoded
  fallback, but is undiscoverable next to the rest of `core/`'s declared config keys.
- [ ] **Code index DB (+ WAL/shm files) not gitignored** — `.promptwise/code_index.sqlite3*` will
  dirty `git status` once this verb runs against this repo or is exposed over MCP. Same
  pre-existing gap as `.promptwise/audit.jsonl`, but this branch is the first to write a binary,
  always-regenerable artifact there.
- [ ] **Stale-row sweep isn't scoped to `root`** — `query_code_index` never normalizes `root`
  (no `.resolve()`), so a relative vs. absolute `root` for the same repo produces disjoint file
  keys and the incremental-reindex sweep silently degrades to a full reparse; a shared DB across
  two roots would delete each other's rows. Correctness holds (results always rebuild), only the
  incremental-reindex guarantee is at risk. Fix: normalize `root` and/or scope the sweep query.
- [ ] **No `check_policy`/`record_audit` on the verb's fs/DB access** — against goal 4's "every
  fs/shell/DB/cloud action is governed and audited", but the spec/plan are silent on it and
  existing precedent is mixed (`fs.py` gates writes, `verify_output` doesn't gate its shell-outs).
  Decide explicitly before the follow-up task that exposes `query_code_index` over MCP — that's
  the point an untrusted agent, not core itself, picks `root`.
- [ ] **Plan's own post-plan follow-ups** — MCP tool exposure for `query_code_index` (mirrors
  `verify_output`'s wrapper in `gateway/mcp_server.py`); reference-finding ("what calls Y") as a
  natural extension of the same store, needs its own query captures + spec section.
- [ ] Symlink-cycle regression test (`test_query_code_index_does_not_follow_a_symlinked_
  directory_cycle`) is skipped on this dev machine (no Windows symlink privilege) — confirm it
  actually runs and passes on a Linux/symlink-capable box before relying on the guard in prod.

### Architecture-advisor pack (idea, not started)

Research done 2026-08-24: `docs/research/architecture-patterns-cloud-reference.md` — software architecture pattern decision table (layered, microservices, event-driven, CQRS, DDD, hexagonal, SOA, etc.), cloud service/deployment model reference, AWS/Azure/GCP 2026 comparison, and a 4-question recommendation heuristic. Proposed shape: `packs/registry/architecture-advisor/` (kind: `intelligence`) that takes project context and returns a ranked pattern + cloud recommendation with rationale. Depends on nothing blocking implementation directly, but best sequenced after Phase 5 (spec engine) if it wants structured project-context intake rather than ad hoc prompting.

### Repo-intelligence / methodology packs (blocked, tracked here so it isn't lost)

From `docs/superpowers/specs/2026-08-24-repo-intelligence-methodology-packs-design.md` — content blocked on Phases 3 (`check_policy`/`record_audit`), 4 (code index), 5 (spec engine/`orchestrate_tasks`), none of which exist in code yet.

- [ ] `repo-intelligence` pack (kind: intelligence) — feature/requirements/architecture/pseudocode/design extraction DAG.
- [ ] `bmad-methodology` pack (kind: lifecycle) — Business-model→Architecture→Design→Development DAG.
- [ ] `dmaic-methodology` pack (kind: lifecycle) — Define-Measure-Analyze-Improve-Control DAG.
- [ ] Open questions for whichever plan picks these up: complexity-threshold default for pseudocode extraction (config-tunable?); whether `extract-requirements`' EARS inference reuses Phase 5's spec-engine logic as a shared helper or reimplements it; golden-fixture repo size for the test suite.

### Phase-level (from `docs/ROADMAP.md`)

- [x] **Phase 2 (Verification Gate)** — confirmed 2026-08-24: all four `core/verify/` acceptance criteria have real, passing tests (`core/tests/verify/`), including a genuine end-to-end MCP `call_tool` test (previously only tool-registration was checked). Found and fixed a real bug along the way: `verify_output` resolved org/project config from the *process* cwd instead of the `cwd` argument — broke any MCP caller whose target project differs from the gateway's own working directory. Fixed in `d3978e6`.
- [x] **Phase 3 (Governed system control)** — found already implemented on unmerged branch `worktree-phase3-governed-system-control` (5 commits: check_policy engine, hash-chained audit log, JIT grants, governed fs_write, MCP tool allowlist, support-bundle generator), not previously recorded in session status. Rebased onto master, code-reviewed, 3 real bugs found and fixed before merge (`f2f48fa`): `fs_write` scoped policy by filename only (directory-scoped allow/deny was unexpressible), `undo_buffer_max: 0` didn't disable undo history (Python `[-0:]` slice quirk), audit log's `_last_hash` rescanned the whole file on every write (O(n²) over a session) — fixed with a chunked tail-seek, which surfaced a Windows CRLF line-ending bug fixed alongside it. Merged to master `7b427a2` 2026-08-24, full suite green (198 passed, 1 skipped, pushed to origin).
  - **Deferred, not a blocker:** `record_audit` called inline at 2 call sites within `fs_write` rather than via a shared decorator/middleware (`core/CLAUDE.md`'s stated convention) — acceptable with only one governed verb so far; revisit when the second governed action (e.g. `shell_exec`) is added, so the wrapper pattern is designed against two real call sites, not speculatively.
  - **Deferred, not a blocker:** JIT grants, fs_write, tool_registry, and audit log are all unauthenticated, single-process, cooperative-locking-free JSON/JSONL stores — fine for Phase 0-6's zero-cost single-node target, will need real locking or a DB-backed store if/when multi-process concurrency is introduced.
- [x] **Phase 4 sub-project 1 of 3 (code index)** — `core/index/`: tree-sitter Python/TS/TSX/JS
  definition extraction (`parser.py`), SQLite symbol store with mtime invalidation (`store.py`),
  and the public `query_code_index` verb (`query.py`) tying walk+reindex+query together.
  Individually task-reviewed (Tasks 1-3 clean; Task 4 had 1 major + 4 minor, fixed `da6ce86`),
  then finally whole-branch-reviewed (1 more major + 8 minor found; the major — file-level I/O
  errors crashing the whole query — and a related minor fixed `12d3288`, rest logged above).
  Merged to master `deab912` 2026-08-24, full suite green (226 passed, 4 skipped).
- [ ] **Phase 4 sub-projects 2 & 3 (memory/fact layer, ingestion daemon)** — hybrid BM25+vector
  retrieval + PII exclusion (sub-project 2), the daemon that keeps the code index and memory
  layer fresh without manual reindex calls (sub-project 3). Not started — each needs its own
  brainstorm per `docs/superpowers/specs/2026-08-24-code-index-design.md`'s Decision 2 (deliberately
  shares no code with the code index).
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
