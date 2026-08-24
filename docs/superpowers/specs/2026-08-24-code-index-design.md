# Code Index (tree-sitter) — Design Spec

Status: approved, ready for implementation planning.
Scope: Phase 4 sub-project 1 of 3 (Memory & code context). See `docs/BACKLOG.md`
and `docs/ROADMAP.md` for how this fits the phase as a whole; sub-projects 2
(memory/fact layer — hybrid BM25+vector retrieval, PII exclusion) and 3
(ingestion daemon) are separate, later specs.

## Purpose

Give core and any connected agent a way to answer "where is X defined"
correctly across a multi-file, multi-language repo, without a model call —
a real code index, not a text-grep approximation. This is the concrete
`docs/ROADMAP.md` Phase 4 acceptance criterion: *"tree-sitter index answers
'where is X defined' correctly on a multi-file repo."*

Out of scope for this spec (deliberately, see decisions below):
- Semantic/vector search over code (folds into the memory/fact layer
  sub-project, which already needs an embedding model).
- "What calls Y" / reference-finding (not required by the ROADMAP
  criterion; a natural follow-on once the definition index exists, not
  blocking it).
- A file-watcher/daemon that keeps the index warm in the background
  (that's the ingestion-daemon sub-project) — this index re-indexes
  inline, synchronously, on query.
- MCP tool exposure — this ships as a core verb + tests, callable directly
  like `verify_output` is by `core/verify/gate.py`'s own tests. Wiring an
  MCP tool for it is a small, separate follow-on once the verb is stable.

## Decisions (from brainstorming)

1. **Language support is core-bundled, not pack-extensible.** Core ships a
   fixed, small grammar set (Python, TypeScript, TSX, JavaScript — this
   repo's own two implementation languages plus the dashboard's). This is
   parsing infrastructure, not a stack opinion (no linting rules, no style
   conventions) — it doesn't violate `CLAUDE.md` goal 1's "no stack-specific
   logic in core". Extending to more languages later means adding a grammar
   + query to `core/index/languages.py`, not building pack-extension
   machinery now (YAGNI).
2. **Structural only, no embeddings.** This sub-project answers "where is X
   defined" via exact/substring symbol match against a parsed AST, not
   semantic similarity. Keeps the embedding-model choice (needed for the
   memory/fact layer) out of this sub-project's critical path.
3. **Persisted + incrementally re-indexed**, not a full rebuild per query.
   A SQLite table keyed by `(file, mtime)` lets a query re-parse only files
   that changed since the last query — fast repeat queries on a stable
   repo, no daemon required to get that speed.

## Architecture

```
query_code_index(symbol, kind=None, root=None, config=None)
        │
        ▼
  walk root for known extensions (skip .git/node_modules/__pycache__/venvs)
        │
        ▼
  for each file: compare current mtime vs stored mtime (SQLite)
        │
        ├─ unchanged ──────────────────────────────┐
        │                                            │
        └─ new/changed: parse_file(path)             │
             │ (tree-sitter Query per language)       │
             ▼                                        │
        replace that file's rows in SQLite ───────────┤
                                                        ▼
                                          SELECT symbol/kind/file/line
                                          WHERE symbol matches, ranked
                                          exact-match-first
                                                        │
                                                        ▼
                                          list[CodeLocation]
```

Files present in the SQLite table but no longer on disk have their rows
dropped during the same walk (handles renames/deletes without a separate
GC pass).

## Components

- **`core/index/models.py`** — `CodeLocation(BaseModel)`: `file: str`,
  `line: int`, `symbol: str`, `kind: Literal["function", "class",
  "method"]`. Pydantic v2, matches every other verb's typed-contract
  convention (`core/CLAUDE.md`).
- **`core/index/languages.py`** — a small registry:
  `{".py": PYTHON_LANG, ".ts": TS_LANG, ".tsx": TSX_LANG, ".js": JS_LANG}`,
  each entry pairing a compiled tree-sitter `Language` with a tree-sitter
  `Query` string that captures function/class/method definition nodes and
  their name nodes. Adding a language means adding one entry here.
- **`core/index/parser.py`** — `parse_file(path: Path) -> list[CodeLocation]`.
  Looks up the language by extension (returns `[]` for an unknown
  extension — not an error). Runs the language's Query against the parsed
  tree. tree-sitter is error-tolerant by design (produces `ERROR` nodes
  around unparseable regions rather than failing outright) — this function
  extracts whatever definitions it can find and never raises on malformed
  source.
- **`core/index/store.py`** — SQLite-backed table
  `code_index(symbol, kind, file, line, mtime)`, path resolved via
  `resolve_path(config, "index.db_path", ".promptwise/code_index.sqlite3")`
  — the same config-driven-path convention as the verify ledger and audit
  log. Functions: `get_stored_mtime(conn, file) -> float | None`,
  `replace_file_rows(conn, file, mtime, locations)`,
  `delete_file_rows(conn, file)`, `query_symbol(conn, symbol, kind=None) ->
  list[CodeLocation]` (exact match first, then substring, both
  case-sensitive — code symbols are case-sensitive in every language this
  spec covers).
- **`core/index/query.py`** — `query_code_index(symbol, kind=None,
  root=None, config=None) -> list[CodeLocation]`, the public verb. Ties
  the walk/reindex/query steps together. `root=None` defaults to `Path.cwd()`
  (same convention as `core/packs/registry.py`'s `root` parameter); a
  `root` that doesn't exist returns `[]`, not an error (matches the pack
  loader's missing-install-dir convention).

## Data flow (detail)

1. `query_code_index` resolves `config` (via `resolve_config_auto(root=root)`
   if not passed — same cwd-vs-target-root fix applied to `verify_output`
   in this session applies here from day one, not as a later bugfix).
2. Opens the SQLite index (creating the table if absent).
3. Walks `root` recursively, skipping `.git`, `node_modules`, `__pycache__`,
   `.venv`/`venv`, and any directory starting with `.` except the walk
   root itself. Collects files whose extension is in
   `core/index/languages.py`'s registry.
4. For each such file: `current_mtime = file.stat().st_mtime`. If it
   differs from the stored mtime (or there is no stored row), call
   `parse_file`, then `replace_file_rows`.
5. For each file present in the table but not found during the walk,
   `delete_file_rows`.
6. Runs `query_symbol(conn, symbol, kind)`, returns the results.

## Error handling

- Malformed/syntax-error source file: extract whatever tree-sitter can
  parse, skip the rest, never raise. (tree-sitter's own error recovery
  handles most of this for free — no special-casing needed in
  `parse_file` beyond not crashing on a `None` capture.)
- Unknown file extension: not indexed, not an error.
- `root` doesn't exist: `[]`, not an error.
- A file that disappears between the walk's `iterdir` and the `stat()`
  call (race with an external process): treat as "no longer on disk",
  drop its rows, continue the walk — don't let one vanished file abort
  the whole reindex.
- Symbol not found: `[]`, not an error — same "empty is not a failure"
  convention as `run_command`'s "no command configured" case in
  `core/verify/runners.py`.

## Testing

- **`core/tests/index/test_parser.py`** — one fixture source string per
  language (small, hand-written), asserting `parse_file` returns the
  expected `CodeLocation`s (name, kind, line) for functions, classes, and
  methods (a method is a `function` kind nested inside a `class` body in
  Python; verify the query distinguishes it or documents that it doesn't
  need to — methods can be `kind="method"` if the query can detect
  class-nesting, `kind="function"` otherwise, decided during
  implementation once the actual tree-sitter query is written and
  verified against real parse trees).
- **`core/tests/index/test_store.py`** — insert/query roundtrip,
  mtime-based row replacement (insert, bump mtime, replace, confirm old
  rows gone), stale-file row deletion.
- **`core/tests/index/test_query.py`** — integration test on a `tmp_path`
  fixture repo with 2-3 Python files and 1 TypeScript file, each defining
  a few functions/classes, querying for symbols and asserting correct
  file+line. Also: querying a repo with a syntax-error file still returns
  correct results for the other files (proves error-tolerance end to end,
  not just at the parser-unit level). Also: a second query after editing
  one file's content picks up the change (proves mtime invalidation, not
  just a stale cache).

## New dependency

`tree-sitter` (core Python bindings) plus per-language grammar packages —
`tree-sitter-python`, `tree-sitter-typescript` (covers both `.ts`/`.tsx`),
`tree-sitter-javascript`. Add to `pyproject.toml`'s `dependencies`, not
`dev` — this ships as a real core capability, not a test-only tool.

## Open questions for the plan (not blocking, resolve during implementation)

- Exact tree-sitter Query syntax per language — write and hand-verify
  against a real parse tree before locking the test fixtures' expected
  output, rather than guessing capture names up front.
- Whether `kind="method"` needs a dedicated query capture or can be
  derived by checking the definition node's ancestor chain for a class
  body — a plan-time implementation detail, doesn't change this spec's
  public contract (`CodeLocation.kind` is still one of the three
  literals either way).
