# Design: Memory & Fact Layer (Phase 4 sub-project 2 of 3)

Scope: Phase 4 sub-project 2 of 3 ("Memory & code context" in `docs/ROADMAP.md`).
Sub-project 1 (code index — tree-sitter symbol search) is done, merged
`deab912`. Sub-project 3 (ingestion daemon — continuous session/folder
watching) is separate and later; this sub-project ships `record_memory`/
`query_memory` as on-demand verbs, populated by an explicit caller, not
a background watcher.

Ground truth: `docs/research/aug2026-findings.md` (P4, P10; memory/fact
layer table), `docs/research/v3-implementation-plan.md` (Phase 3 —
"Self-Hosted Memory & RAG"), `docs/ROADMAP.md`, root `CLAUDE.md` goals
1-6, `core/CLAUDE.md` conventions.

## Problem

The project's own root `CLAUDE.md` observes: cross-session memory is
the weakest link in every mainstream coding-agent tool. This repo's own
multi-session work (see `agentic-os-session-status` memory file
pattern) already hand-rolls what this sub-project should provide as a
verb: durable facts/decisions that persist across sessions and can be
retrieved by relevance, not just chronology.

Acceptance criterion from `docs/research/aug2026-findings.md` Phase 3:
*"Given a fact from last week's session, when asked today, then it
appears in top-3 retrieval."*

## Out of scope (deliberately)

- General RAG over arbitrary docs/files — this ships fact/decision
  extraction only (Mem0-style), not a document-chunking pipeline. A
  future sub-project can add `kind="doc_chunk"` to the same store
  without redesigning it.
- Continuous ingestion (watched folders, session auto-capture) — that's
  sub-project 3's job. This sub-project's verbs are called explicitly.
- Org-level scope / multi-tenancy — no auth or user-identity concept
  exists anywhere in `core/` yet to hang it off. Only `session` and
  `project` scope for now.
- Semantic code search — folds into the code index's future work
  (`docs/superpowers/specs/2026-08-24-code-index-design.md` already
  calls this out), not duplicated here.

## Decisions

1. **Facts, not chunks.** `record_memory(text)` runs the input through
   a local-model extraction step that returns structured fact
   statements (`"user prefers pytest over unittest"`, category
   `preference`), not the raw text verbatim. Keeps retrieval precise
   (a fact is one idea, not a paragraph) and matches the acceptance
   criterion's phrasing ("a fact... appears in top-3 retrieval").
2. **Hybrid BM25 + vector, fused by RRF**, per the phase's own
   requirement — lexical search alone misses paraphrases ("test
   framework" vs "pytest"), vector alone misses exact terms/IDs. SQLite
   FTS5 for BM25 (same DB the code index already uses as a pattern, no
   new datastore for the lexical half), Qdrant for vectors (locked
   stack dependency, already in `docker-compose`).
3. **Ollama for embeddings, local-small tier for extraction** — zero
   new runtime dependency (`CLAUDE.md`'s locked stack already requires
   Ollama), zero cost (goal 5), and both are swappable later via config
   (bigger embedding model, bigger extraction tier) without a code
   change — the model name is a config value, not a constant.
4. **PII is flagged, never scrubbed at rest.** A flagged fact stays in
   local storage at full fidelity (it's the user's own machine); the
   flag only gates whether `query_memory` includes it when assembling
   cloud-bound context (`allow_pii=False`). Matches
   `docs/research/aug2026-findings.md`'s acceptance criterion: *"Given
   a PII-flagged chunk, when cloud context is assembled, then it is
   excluded and the exclusion audited."*
5. **`core/diagnostics/redact.py` gains a detector, not a second
   redaction path.** `MAINTENANCE.md`'s single-redaction-path rule
   means PII detection extends the existing module (secret patterns +
   new email/phone patterns) rather than a memory-scoped classifier
   living in `core/memory/`.
6. **Error handling matches the code index's now-established
   convention**: unreachable Ollama, unreachable Qdrant, a non-directory
   `root` are all handled states (fallback/degrade/`[]`), never
   exceptions that abort the whole call. This was a real, twice-found
   bug class in the code-index sub-project's reviews — designing it in
   from the start here instead of discovering it in review.

## Architecture

```
core/memory/
  __init__.py
  models.py    Fact (Pydantic v2): id, text, category, scope, root, pii, created_at, session_id
  embed.py     embed_text(text, config) -> list[float], via Ollama HTTP /api/embeddings
  extract.py   extract_facts(text, config) -> list[dict], via route_request (local-small tier)
  store.py     SQLite: facts table + FTS5 virtual table, scope-keyed CRUD + BM25 search
  vectors.py   Qdrant wrapper: upsert_fact(fact, vector), search(query_vector, scope, root, limit)
  rank.py      reciprocal_rank_fusion(bm25_results, vector_results, k=60) -> merged ranked list
  memory.py    public verbs: record_memory(text, scope, root=None) -> list[Fact];
               query_memory(query, scope, root=None, allow_pii=True, limit=10) -> list[Fact]
```

Mirrors `core/index/`'s file-per-concern convention (parser/store/query
split there → embed/extract/store/vectors/rank/memory split here) —
same reasoning: each unit answers "what does it do, how do you use it,
what does it depend on" independently, and can be tested in isolation.

## Data flow

**`record_memory(text, scope, root=None)`**
1. `redact.contains_pii(text)` → `pii: bool` flag (detection only, text
   stored unmodified).
2. `extract_facts(text, config)` — local-model call via `route_request`
   (tier hint `local-small`), returns `[{text, category}, ...]`. On
   Ollama-unreachable: fallback to one fact = the whole input text,
   category `unclassified` — never raises.
3. For each extracted fact: `embed_text(fact.text, config)` → vector.
   On Ollama-unreachable: skip the vector, fact is still saved
   (BM25-searchable, just not vector-searchable) — logged, not raised.
4. `store.save_fact(fact, scope, root, session_id)` → SQLite row +
   FTS5 index entry.
5. If a vector was produced: `vectors.upsert_fact(fact_id, vector,
   payload={scope, root, pii, category})` → Qdrant. On
   Qdrant-unreachable: same degrade-not-raise as step 3.
6. `record_audit("memory.record", {scope, root, pii, fact_count})` at
   the boundary (one call site, not scattered — `core/CLAUDE.md`'s
   convention).
7. Returns the saved `list[Fact]`.

**`query_memory(query, scope, root=None, allow_pii=True, limit=10)`**
1. `store.search_fts(query, scope, root)` → BM25-ranked `list[Fact]`.
   Non-directory/missing `root` → `[]` early, no exception (matches the
   code-index fix).
2. `embed_text(query, config)` → query vector. On Ollama-unreachable:
   skip to BM25-only results.
3. `vectors.search(query_vector, scope, root, limit=20)` → Qdrant
   results. On Qdrant-unreachable: skip to BM25-only results.
4. `rank.reciprocal_rank_fusion(bm25_results, vector_results)` → merged
   ranked list.
5. If `allow_pii=False`: filter out `pii=True` facts; if any were
   filtered, `record_audit("memory.pii_excluded", {scope, root,
   excluded_count})`.
6. Return top `limit` `Fact` objects.

## Storage schema

**SQLite** (`.promptwise/memory.sqlite3`, config key `memory.db_path`,
same `resolve_path` convention as the code index's `index.db_path`):

```sql
CREATE TABLE facts (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    category TEXT NOT NULL,
    scope TEXT NOT NULL,            -- 'session' | 'project'
    root TEXT,                      -- normalized project root; NULL for session scope
    session_id TEXT,                -- set for scope='session'
    pii INTEGER NOT NULL DEFAULT 0, -- 0/1
    created_at REAL NOT NULL
);
CREATE VIRTUAL TABLE facts_fts USING fts5(text, content='facts', content_rowid='id');
CREATE INDEX idx_facts_scope_root ON facts(scope, root);
```

BM25 ranking via SQLite FTS5's built-in `bm25()` function — no external
lexical search dependency.

**Qdrant** collection `promptwise_memory`, vector size = embedding
model's dimension (768 for the default `nomic-embed-text`), payload
`{fact_id, scope, root, pii, category}`, filtered by `scope`/`root` on
search (Qdrant payload filter, not a separate collection per project —
avoids collection-count blowup as projects grow).

## Config additions (`core/config/defaults.yaml`)

```yaml
memory:
  db_path: .promptwise/memory.sqlite3
  qdrant_url: http://localhost:6333
  embedding_model: nomic-embed-text
  extraction_tier_hint: local-small
```

## Testing strategy

- TDD per module (`superpowers:test-driven-development`), failing test
  before implementation, same as `core/index/`.
- `embed.py`/`extract.py`: unit tests mock the Ollama HTTP call
  (`responses`/`unittest.mock`, no real network) — deterministic, fast.
- `vectors.py`: tests use `QdrantClient(":memory:")` — no Docker
  dependency for dev/CI, matches the decision above.
- `store.py`: direct SQLite tests, same pattern as
  `core/tests/index/test_store.py`.
- `rank.py`: pure-function unit tests over hand-built ranked lists — no
  I/O.
- `memory.py`: integration tests wiring the real modules together with
  the in-memory Qdrant client and mocked Ollama calls — deterministic,
  no flaky network dependency in the default test run.
- One `requires_ollama`-gated test (skipif, same convention as
  `requires_symlinks` in `core/tests/packs/test_registry.py` and the
  gitleaks-binary skip) that hits a real local Ollama instance if one
  is running, to catch real-integration drift — skipped in CI/sandboxes
  without Ollama.
- Explicit regression tests for every "handled state, not exception"
  case in Data Flow above (Ollama down at extract, Ollama down at
  embed, Qdrant down at query, non-directory root) — this is exactly
  the class of bug the code-index sub-project's two review rounds kept
  finding late; designing the tests in from Task 1 here instead.

## Global Constraints (carried forward from the code-index plan, still binding)

- Core stays language/domain-agnostic — no `if scope == "project"`
  branching that leaks into pack-specific logic.
- No verb reads a config file directly — always through
  `core/config/resolve.py`.
- `resolve_config_auto(root=<target root>)`, never process cwd (the
  Phase-2 bug class — do not reintroduce).
- Pydantic v2 models for the typed contract (`Fact`).
- Never crash on malformed input: unreachable Ollama/Qdrant, a
  non-directory root, an empty/whitespace-only `text` input are all
  handled states, not exceptions.
- TDD, failing test before implementation, for every module.

## Open questions for the implementation plan

- Exact RRF `k` constant (60 is the common default in IR literature —
  confirm no reason to deviate) and tie-breaking order when a fact
  appears in both BM25 and vector result sets.
- Whether `extract_facts`' local-model prompt needs few-shot examples
  to reliably emit valid JSON on the smallest catalog tier, or whether
  a retry-with-fallback (same convention as `parse_file` tolerating
  syntax errors) is enough — needs hand-verification against the real
  installed Ollama model before the plan's code is written, same
  discipline as the code-index plan's tree-sitter API pre-verification.
- Session-scope TTL/cleanup (facts accumulate indefinitely otherwise)
  — not in the phase's acceptance criteria, but worth deciding before
  implementation rather than after.

## Post-plan follow-ups (log to `docs/BACKLOG.md` if not picked up immediately)

- MCP tool exposure for `record_memory`/`query_memory` (mirrors
  `verify_output`'s and the code index's eventual MCP wrapper).
- `kind="doc_chunk"` extension for general RAG (deliberately deferred
  above).
- Sub-project 3 (ingestion daemon) calling `record_memory` on a
  schedule/watch — the natural consumer of this sub-project's verbs.
