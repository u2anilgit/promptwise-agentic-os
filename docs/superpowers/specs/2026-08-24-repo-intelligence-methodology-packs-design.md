# Design: Repo-Intelligence Pack + Methodology Packs

**Date:** 2026-08-24
**Status:** Approved (pending spec review gate)
**Authors:** brainstorming session, u2anil + Claude

## Context

`CLAUDE.md`, `docs/VISION.md`, and `docs/ROADMAP.md` define a generic core engine plus installable packs carrying all domain knowledge (`ARCHITECTURE.md` §3). Two gaps were identified against that plan:

1. **No general existing-repo reverse-engineering.** Phase 4 (memory & code context) gives retrieval ("where is X defined"); Phase 9 (Migration Factory) has an `analyzer` DAG stage, but scoped narrowly to migration prep for a specific source→target pair. Nothing produces standalone feature/requirements/architecture/pseudocode/design documentation from an arbitrary existing codebase.
2. **No pluggable delivery methodology.** The spec engine (Phase 5) hardcodes one SDLC-style pipeline (`specify → plan → tasks → implement → verify`). Other methodologies referenced by the user (BMAD, DMAIC) have no home in the current design.

Both gaps are addressable entirely within the existing pack architecture — no core-engine verb changes, no restructuring of the spec engine. This document specs that extension.

## Goals

- Ship a pack that reverse-engineers an existing repo into reviewable documentation: features, requirements (EARS-format), architecture-as-implemented, pseudocode/algorithms, and design/ADR reconstruction.
- Ship two methodology packs (BMAD, DMAIC) as alternate, opt-in workflow DAGs, without touching the spec engine's default SDLC pipeline.
- Add exactly one schema-level change (`intelligence` as a new pack kind); zero core-engine code changes.

## Non-goals

- No new core-engine verb. Everything rides on `orchestrate_tasks`, `verify_output`, `rank_context`, `check_policy`, `record_audit`, and the Phase 4 code index.
- No change to the spec engine's default `specify/plan/tasks/implement/verify` pipeline — it remains the SDLC default; methodology packs are additive, not a replacement.
- No queryable-memory-index output in this round (doc artifacts in-repo only, per decision below). Indexing extracted facts into `query_memory` is a possible future pack version, not v1.
- No multi-repo/org-wide catalog — single-repo, on-demand analysis only.

## Decisions from brainstorming

| Question | Decision |
|---|---|
| Extraction output form | Doc artifacts written into the target repo (not memory-index-only) |
| Methodology fit | Pack-level DAG templates via `orchestrate_tasks`, spec engine unchanged |
| V1 extraction scope | All four: features/requirements, architecture-as-implemented, pseudocode/algorithms, design/ADR reconstruction |
| Pack taxonomy | New `intelligence` pack kind (distinct from `architecture` and `lifecycle`) |
| Phasing | Folds into existing Phase 8 ("Intelligence Packs v1"), still gated on Phase 4 (code index) |

## Architecture

No changes to the layering diagram in `ARCHITECTURE.md` §1. Two new packs are added under `packs/registry/`, using only existing core verbs:

```
repo-intelligence (kind: intelligence)   → orchestrate_tasks, rank_context, check_policy, code index (Phase 4)
bmad-methodology  (kind: lifecycle)      → orchestrate_tasks, verify_output, record_audit
dmaic-methodology (kind: lifecycle)      → orchestrate_tasks, verify_output, record_audit
```

### 1. Pack kind schema change

`pack.yaml`'s `kind` field gains one enum value:

```yaml
kind: stack | database | cloud-devops | architecture | migration | lifecycle | intelligence
```

`intelligence` packs reverse-engineer existing systems into documentation. This is distinct from:
- `architecture` packs, which are forward-looking/prescriptive (pattern advisor, ADR *generation* for new work, anti-pattern detection during development).
- `lifecycle` packs, which capture requirements *for new work* (EARS criteria authoring, release notes, runbooks).

This matches the naming already used in `CLAUDE.md`'s repo map and `ROADMAP.md` Phase 8's title ("Intelligence Packs v1") — the new kind is a natural fit under an already-named umbrella, not a new concept.

### 2. `repo-intelligence` pack

`packs/registry/repo-intelligence/`, `kind: intelligence`.

```yaml
name: repo-intelligence
version: 1.0.0
kind: intelligence
summary: Reverse-engineers an existing repo into feature, requirements, architecture, pseudocode, and design documentation
requires_core: ">=0.4.0,<0.5.0"   # depends on Phase 4 code index being present
capabilities:
  - fs:read
  - fs:write:docs/reverse-engineered/**
dependencies: []
```

One `orchestrate_tasks` DAG, six nodes:

| Node | Reads | Writes | Notes |
|---|---|---|---|
| `scan` | Phase 4 code index (tree-sitter) | in-memory module/dependency graph | entry point for all downstream nodes |
| `extract-features` | scan output, `rank_context`-budgeted source reads | `features.md` | enumerated capabilities, entry points, public APIs |
| `extract-requirements` | scan output, tests, `extract-features` output | `requirements.md` | EARS-format, inferred from observed behavior + test assertions |
| `extract-architecture` | scan output | `architecture.md` | component map, dependency graph, detected patterns; diffed against existing `docs/ARCHITECTURE.md` if present, calling out drift |
| `extract-pseudocode` | scan output | `algorithms/<module>.md` | plain-language pseudocode for functions above a complexity threshold (config-tunable, default: cyclomatic complexity ≥ 10) |
| `extract-design` | all prior node outputs | `design.md` | ADR-style reconstruction of inferred design decisions — lowest-confidence node, output explicitly banner-labeled |
| `synthesize` | all extraction outputs | index file linking all docs | final node; writes everything under one target directory |

Output location: `<target-repo>/docs/reverse-engineered/` by default, overridable via the standard 5-layer config (`ARCHITECTURE.md` §4) to `.promptwise/repo-intel/` or elsewhere. Every generated file carries a banner:

```
<!-- Generated by repo-intelligence pack vX.Y.Z. Source commit: <sha>. Generated: <date>.
     Advisory only — verify before treating as ground truth. -->
```

All `fs:write` calls go through `check_policy` exactly like any other pack action (`ARCHITECTURE.md` §7) — no special-cased bypass for "just generating docs."

### 3. Methodology packs

`packs/registry/bmad-methodology/` and `packs/registry/dmaic-methodology/`, both `kind: lifecycle`.

```yaml
name: bmad-methodology
version: 1.0.0
kind: lifecycle
summary: BMAD (Business-model, Architecture, Design, Development) workflow DAG, alternate to the default SDD spec-engine pipeline
requires_core: ">=0.5.0,<0.6.0"   # depends on Phase 5 spec engine / orchestrate_tasks maturity
capabilities:
  - fs:write:docs/**
dependencies: []
```

```yaml
name: dmaic-methodology
version: 1.0.0
kind: lifecycle
summary: DMAIC (Define, Measure, Analyze, Improve, Control) workflow DAG, alternate to the default SDD spec-engine pipeline
requires_core: ">=0.5.0,<0.6.0"
capabilities:
  - fs:write:docs/**
dependencies: []
```

Each pack contributes its own `dags/` template run directly via `orchestrate_tasks` — **not** through the spec engine's `specify/plan/tasks/implement/verify` state machine. The spec engine is untouched and remains the SDLC default for any project that doesn't opt into a methodology pack.

Stage mapping:
- **BMAD**: `business-model → architecture → design → development`, where `development`'s output must pass `verify_output` before the DAG node is marked complete (same hard gate as the spec engine's `implement` step — CLAUDE.md goal 3 has no pack-level exception).
- **DMAIC**: `define → measure → analyze → improve → control`, where `improve`'s output (the actual code/process change) must pass `verify_output` before completion; `control` writes a monitoring/runbook artifact (ties into `MAINTENANCE.md`'s troubleshooting KB pattern).

Every node in both DAGs calls `record_audit`, identical to spec-engine steps — no reduced audit trail for choosing a non-default methodology.

Project selects an active methodology pack via the existing config layers (`ARCHITECTURE.md` §4) — e.g. `promptwise.config.yaml`:

```yaml
active_methodology: bmad-methodology   # or dmaic-methodology, or omit for default spec-engine SDD pipeline
```

## Data flow

```
existing repo
   │
   ▼
repo-intelligence.scan  (reads Phase 4 code index)
   │
   ├──► extract-features ─────► features.md
   ├──► extract-requirements ──► requirements.md   (reads extract-features output too)
   ├──► extract-architecture ──► architecture.md
   ├──► extract-pseudocode ────► algorithms/*.md
   └──► extract-design ────────► design.md         (reads all prior outputs)
              │
              ▼
          synthesize ──► docs/reverse-engineered/index.md
```

Methodology packs are independent of repo-intelligence — either can run standalone. A likely combined use case (not required for v1): run `repo-intelligence` first on a legacy repo to establish an as-built baseline, then start new work on that repo through a methodology pack's DAG, informed by the generated docs via `rank_context`.

## Error handling

- Extraction nodes are **best-effort/advisory**, never a hard gate. A node that fails on a malformed/unparseable file logs the failure and skips that file, continuing the DAG — this is categorically different from `verify_output`, which blocks on failure by design (CLAUDE.md goal 3 applies to *code changes*, not to documentation generation about existing code).
- `extract-design` (ADR reconstruction) is the lowest-confidence node — inference beyond static analysis. Its output always carries an explicit confidence banner and is never treated as authoritative by any other core verb or pack.
- Methodology pack DAG nodes that reach an actual code-change step (BMAD's `development`, DMAIC's `improve`) are hard-gated by `verify_output` exactly like the spec engine's `implement` step — no weaker gate for choosing an alternate methodology.

## Testing

- **repo-intelligence**: small multi-file fixture repos with known features/architecture checked into the pack's test directory; DAG run against each fixture, output diffed against golden docs. Complexity-threshold pseudocode extraction tested against a fixture function with known cyclomatic complexity.
- **bmad-methodology / dmaic-methodology**: DAG run against a stub task; test asserts stage sequence matches the methodology's defined order, `verify_output` is actually invoked at the code-change node, and the audit trail records every stage transition.

## Roadmap change

`docs/ROADMAP.md` Phase 8 ("Intelligence Packs v1") acceptance criteria gains two additions, still gated on Phase 4 (code index) completing first:

- `repo-intelligence` pack produces all four doc types (features, requirements, architecture, pseudocode) plus the lower-confidence design/ADR doc on a real sample repo, each carrying the advisory banner.
- `bmad-methodology` and `dmaic-methodology` packs each run one DAG end-to-end against a stub task with an intact, verifiable audit trail, and without altering spec-engine behavior for projects that don't opt in.

No other phase's acceptance criteria change. No core-engine verb table (`ARCHITECTURE.md` §2) entries change.

## Open questions for implementation planning

- Exact complexity-threshold default and whether it's config-tunable per-pack or per-project (leaning per-project, via standard config layers).
- Whether `extract-requirements`' EARS inference reuses the Phase 5 spec engine's EARS-authoring logic (as a shared library) or reimplements it pack-side — reuse is preferable if Phase 5 exposes it as a callable helper, not a spec-engine-internal.
- Golden-fixture repo size/complexity for the test suite — needs enough surface area to exercise all four extraction types without becoming an unmaintainable fixture.
