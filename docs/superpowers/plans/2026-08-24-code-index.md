# Code Index (tree-sitter) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `query_code_index`, a core verb that answers "where is X defined" correctly across a multi-file, multi-language (Python/TypeScript/TSX/JavaScript) repo, backed by a persisted, incrementally-reindexed tree-sitter symbol table.

**Architecture:** Walk the repo for known file extensions, compare each file's mtime against a SQLite-stored value, reparse only changed files with a per-language tree-sitter Query that captures function/class/method definitions, replace that file's rows, then answer the query with a SELECT (exact match ranked before substring).

**Tech Stack:** `tree-sitter` 0.26 Python bindings + `tree-sitter-python`, `tree-sitter-typescript` (covers `.ts`/`.tsx`), `tree-sitter-javascript` grammar packages. SQLite via the stdlib `sqlite3` module (no new ORM dependency — this is a small, single-table store, consistent with the ledger/audit log's plain-JSON-file tier of complexity, just needing SQL's indexed lookup instead of JSON).

**Spec:** `docs/superpowers/specs/2026-08-24-code-index-design.md`

## Global Constraints

- Core stays language-agnostic in *behavior*: the fixed grammar set is parsing infrastructure, not a stack opinion — see spec Decision 1.
- No embeddings/vector search in this sub-project — see spec Decision 2.
- Every verb call uses Pydantic v2 models for its typed contract (`core/CLAUDE.md`).
- No verb reads a config file directly — always through `core/config/resolve.py` (`resolve_path`/`resolve_config_auto`).
- `resolve_config_auto` must be called with `root=<the target root>`, never left to default to process cwd — this project's Phase 2 session found and fixed exactly this bug in `verify_output`; don't reintroduce it here.
- TDD: failing test before implementation, every task.
- Never crash on malformed input: unparseable source, unknown extensions, missing directories, and races (file vanishes mid-walk) are all handled states, not exceptions — matches the fail-open convention in `core/verify/ledger.py` and `core/packs/registry.py`.

---

### Task 1: Dependencies, models, and the Python parser (first vertical slice)

**Files:**
- Modify: `pyproject.toml` (add tree-sitter deps to `dependencies`, not `dev`)
- Create: `core/index/__init__.py` (empty, matches `core/verify/__init__.py`'s convention)
- Create: `core/index/models.py`
- Create: `core/index/languages.py`
- Create: `core/index/parser.py`
- Test: `core/tests/index/__init__.py` (empty)
- Test: `core/tests/index/test_parser.py`

**Interfaces:**
- Produces: `CodeLocation(BaseModel)` with fields `file: str`, `line: int`, `symbol: str`, `kind: Literal["function", "class", "method"]` — every later task imports this from `core.index.models`.
- Produces: `LANGUAGES: dict[str, LanguageSpec]` in `core.index.languages`, keyed by file extension (e.g. `".py"`) — one `LanguageSpec` per extension (not per definition-kind), where `LanguageSpec` is a small dataclass `{language: tree_sitter.Language, query: tree_sitter.Query}`. Every language's `query` uses the same three fixed capture-name pairs (`func.def`/`func.name`, `class.def`/`class.name`, `method.def`/`method.name`) — a language that has no methods as a distinct node type (Python) simply never produces `method.*` captures, so `parser.py` can check for all three pairs unconditionally regardless of language.
- Produces: `parse_file(path: Path) -> list[CodeLocation]` in `core.index.parser` — Task 3's store and Task 4's query verb both call this directly.

- [ ] **Step 1: Add the tree-sitter dependencies**

Edit `pyproject.toml`'s `dependencies` list:

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.8",
    "pyyaml>=6.0",
    "typer>=0.12",
    "mcp>=1.2",
    "tree-sitter>=0.26",
    "tree-sitter-python>=0.25",
    "tree-sitter-typescript>=0.23",
    "tree-sitter-javascript>=0.25",
]
```

Run: `pip install -e .`
Expected: installs cleanly (these are already installed in this dev environment from spec-verification — this step makes it reproducible for any other environment/CI).

- [ ] **Step 2: Write the failing test for `CodeLocation`**

`core/tests/index/test_parser.py`:

```python
from pathlib import Path

from core.index.models import CodeLocation


def test_code_location_requires_all_fields():
    loc = CodeLocation(file="a.py", line=3, symbol="foo", kind="function")
    assert loc.file == "a.py"
    assert loc.line == 3
    assert loc.symbol == "foo"
    assert loc.kind == "function"
```

- [ ] **Step 2b: Run test to verify it fails**

Run: `pytest core/tests/index/test_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.index'`

- [ ] **Step 3: Create the package and the model**

`core/index/__init__.py`: empty file.

`core/tests/index/__init__.py`: empty file.

`core/index/models.py`:

```python
# core/index/models.py
from typing import Literal

from pydantic import BaseModel


class CodeLocation(BaseModel):
    file: str
    line: int
    symbol: str
    kind: Literal["function", "class", "method"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest core/tests/index/test_parser.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for the Python parser**

Append to `core/tests/index/test_parser.py`:

```python
from core.index.parser import parse_file


def test_parse_file_extracts_python_function_and_class(tmp_path):
    source = (
        "def foo(x):\n"
        "    return x\n"
        "\n"
        "class Bar:\n"
        "    def method_a(self):\n"
        "        pass\n"
    )
    py_file = tmp_path / "sample.py"
    py_file.write_text(source, encoding="utf-8")

    locations = parse_file(py_file)
    by_symbol = {loc.symbol: loc for loc in locations}

    assert by_symbol["foo"].kind == "function"
    assert by_symbol["foo"].line == 1  # 1-indexed, tree-sitter rows are 0-indexed
    assert by_symbol["Bar"].kind == "class"
    assert by_symbol["Bar"].line == 4
    assert by_symbol["method_a"].kind == "method"  # nested inside class Bar
    assert by_symbol["method_a"].line == 5
    assert str(py_file) == by_symbol["foo"].file


def test_parse_file_unknown_extension_returns_empty(tmp_path):
    unknown = tmp_path / "notes.txt"
    unknown.write_text("hello", encoding="utf-8")
    assert parse_file(unknown) == []


def test_parse_file_tolerates_a_syntax_error(tmp_path):
    # tree-sitter's error recovery should still find `foo` even though the
    # file overall doesn't parse cleanly.
    source = "def foo(x):\n    return x\n\ndef broken(:\n"
    py_file = tmp_path / "broken.py"
    py_file.write_text(source, encoding="utf-8")

    locations = parse_file(py_file)
    symbols = {loc.symbol for loc in locations}
    assert "foo" in symbols
```

- [ ] **Step 5b: Run test to verify it fails**

Run: `pytest core/tests/index/test_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.index.parser'`

- [ ] **Step 6: Implement `languages.py` (Python entry only for this task)**

Hand-verified against the actual tree-sitter 0.26 API and Python grammar
before writing this (see spec's "Open questions" note — no guessing):
`function_definition` and `class_definition` both have a `name:` field
holding an `identifier`; a `function_definition` nested inside a
`class_definition`'s `block` is a method — there is no separate node type
for it in the Python grammar, so `kind` is derived by walking `.parent`
looking for an ancestor `class_definition`.

```python
# core/index/languages.py
from dataclasses import dataclass

import tree_sitter_python as tspython
from tree_sitter import Language, Query


@dataclass(frozen=True)
class LanguageSpec:
    language: Language
    query: Query


_PY_LANG = Language(tspython.language())
_PY_QUERY = Query(
    _PY_LANG,
    """
    (function_definition name: (identifier) @func.name) @func.def
    (class_definition name: (identifier) @class.name) @class.def
    """,
)

LANGUAGES: dict[str, LanguageSpec] = {
    ".py": LanguageSpec(_PY_LANG, _PY_QUERY),
}
```

- [ ] **Step 7: Implement `parser.py`**

```python
# core/index/parser.py
"""tree-sitter-backed definition extraction — one Query per language,
run once per file. Error-tolerant by construction: tree-sitter itself
recovers from syntax errors and still yields ERROR nodes around the
broken region rather than failing the whole parse, so this module never
needs special-case exception handling for malformed source.
"""
from __future__ import annotations

from pathlib import Path

from tree_sitter import Parser, QueryCursor

from core.index.languages import LANGUAGES
from core.index.models import CodeLocation


def _is_inside_class(node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type == "class_definition":
            return True
        parent = parent.parent
    return False


def _name_for(def_node, name_nodes) -> str | None:
    # the query's name capture can pick up identifiers from nested/sibling
    # definitions too (e.g. a nested function's name) — narrow to the name
    # node that actually falls inside this def_node's own span. Uses >=,
    # not >: a method_definition node (TS/TSX/JS) starts at its own name
    # token directly (no keyword prefix like def/function/class precedes
    # it), so the name node's start_byte equals def_node's start_byte
    # exactly, not strictly after it — hand-verified against the real
    # grammar output before writing this, not guessed.
    match = next(
        (n for n in name_nodes if n.start_byte >= def_node.start_byte and n.end_byte <= def_node.end_byte),
        None,
    )
    return match.text.decode("utf-8") if match is not None else None


def parse_file(path: Path) -> list[CodeLocation]:
    spec = LANGUAGES.get(path.suffix)
    if spec is None:
        return []

    source = path.read_bytes()
    parser = Parser(spec.language)
    tree = parser.parse(source)
    cursor = QueryCursor(spec.query)
    matches = cursor.matches(tree.root_node)

    locations: list[CodeLocation] = []
    for _pattern_index, captures in matches:
        for def_node in captures.get("func.def", []):
            name = _name_for(def_node, captures.get("func.name", []))
            if name is None:
                continue
            # Python has no distinct "method" node — a function_definition
            # nested inside a class body is a method; every other grammar
            # this module supports has a separate method_definition node
            # (below), so this ancestor check only ever fires for Python.
            kind = "method" if _is_inside_class(def_node) else "function"
            locations.append(
                CodeLocation(file=str(path), line=def_node.start_point[0] + 1, symbol=name, kind=kind)
            )
        for def_node in captures.get("class.def", []):
            name = _name_for(def_node, captures.get("class.name", []))
            if name is None:
                continue
            locations.append(
                CodeLocation(file=str(path), line=def_node.start_point[0] + 1, symbol=name, kind="class")
            )
        for def_node in captures.get("method.def", []):
            name = _name_for(def_node, captures.get("method.name", []))
            if name is None:
                continue
            locations.append(
                CodeLocation(file=str(path), line=def_node.start_point[0] + 1, symbol=name, kind="method")
            )

    return locations
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest core/tests/index/test_parser.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml core/index/__init__.py core/index/models.py core/index/languages.py core/index/parser.py core/tests/index/__init__.py core/tests/index/test_parser.py
git commit -m "feat(index): tree-sitter Python definition extraction"
```

---

### Task 2: TypeScript, TSX, and JavaScript support

**Files:**
- Modify: `core/index/languages.py`

**Interfaces:**
- Consumes: `LanguageSpec` (Task 1) — same dataclass, new entries, no changes to the dataclass itself.
- Consumes: `parse_file` (Task 1) — no changes needed. Task 1's `parser.py` already checks for `method.def`/`method.name` captures (Python's query just never produces them, since Python has no distinct method node type — its methods stay under `func.def`, marked via `_is_inside_class`). TS/TSX/JS's `method_definition` is a distinct node type in their grammars (confirmed by hand-testing), so their queries populate `method.def`/`method.name` directly — no ancestor-walk needed for them.
- Test: `core/tests/index/test_parser.py`

- [ ] **Step 1: Write the failing tests**

Append to `core/tests/index/test_parser.py`:

```python
def test_parse_file_extracts_typescript_function_class_method(tmp_path):
    source = (
        "function foo(x) { return x; }\n"
        "\n"
        "class Bar {\n"
        "  methodA() { return 1; }\n"
        "}\n"
    )
    ts_file = tmp_path / "sample.ts"
    ts_file.write_text(source, encoding="utf-8")

    locations = parse_file(ts_file)
    by_symbol = {loc.symbol: loc for loc in locations}

    assert by_symbol["foo"].kind == "function"
    assert by_symbol["Bar"].kind == "class"
    assert by_symbol["methodA"].kind == "method"


def test_parse_file_extracts_tsx(tmp_path):
    source = "function Widget(props) { return null; }\n"
    tsx_file = tmp_path / "widget.tsx"
    tsx_file.write_text(source, encoding="utf-8")

    locations = parse_file(tsx_file)
    assert {loc.symbol for loc in locations} == {"Widget"}


def test_parse_file_extracts_javascript(tmp_path):
    source = (
        "function foo(x) { return x; }\n"
        "class Bar {\n"
        "  methodA() { return 1; }\n"
        "}\n"
    )
    js_file = tmp_path / "sample.js"
    js_file.write_text(source, encoding="utf-8")

    locations = parse_file(js_file)
    by_symbol = {loc.symbol: loc for loc in locations}
    assert by_symbol["foo"].kind == "function"
    assert by_symbol["Bar"].kind == "class"
    assert by_symbol["methodA"].kind == "method"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest core/tests/index/test_parser.py -k "typescript or tsx or javascript" -v`
Expected: FAIL — TS/TSX/JS files return `[]` (extension not in `LANGUAGES` yet)

- [ ] **Step 3: Add the TS/TSX/JS language entries**

Hand-verified node shapes (see spec's open-questions note): TypeScript's
`class_declaration` name field holds a `type_identifier`; JavaScript's
(and TSX inherits TypeScript's grammar) holds a plain `identifier` for
JS. `method_definition` is a distinct node type in both grammars, with a
`name:` field holding a `property_identifier` — no ancestor-walk needed.

Add to `core/index/languages.py`:

```python
import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript

_TS_LANG = Language(tstypescript.language_typescript())
_TS_QUERY = Query(
    _TS_LANG,
    """
    (function_declaration name: (identifier) @func.name) @func.def
    (class_declaration name: (type_identifier) @class.name) @class.def
    (method_definition name: (property_identifier) @method.name) @method.def
    """,
)

_TSX_LANG = Language(tstypescript.language_tsx())
_TSX_QUERY = Query(
    _TSX_LANG,
    """
    (function_declaration name: (identifier) @func.name) @func.def
    (class_declaration name: (type_identifier) @class.name) @class.def
    (method_definition name: (property_identifier) @method.name) @method.def
    """,
)

_JS_LANG = Language(tsjavascript.language())
_JS_QUERY = Query(
    _JS_LANG,
    """
    (function_declaration name: (identifier) @func.name) @func.def
    (class_declaration name: (identifier) @class.name) @class.def
    (method_definition name: (property_identifier) @method.name) @method.def
    """,
)

LANGUAGES[".ts"] = LanguageSpec(_TS_LANG, _TS_QUERY)
LANGUAGES[".tsx"] = LanguageSpec(_TSX_LANG, _TSX_QUERY)
LANGUAGES[".js"] = LanguageSpec(_JS_LANG, _JS_QUERY)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest core/tests/index/test_parser.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 5: Commit**

```bash
git add core/index/languages.py core/tests/index/test_parser.py
git commit -m "feat(index): TypeScript, TSX, and JavaScript definition extraction"
```

---

### Task 3: SQLite-backed store with mtime invalidation

**Files:**
- Create: `core/index/store.py`
- Test: `core/tests/index/test_store.py`

**Interfaces:**
- Consumes: `CodeLocation` (Task 1).
- Produces: `open_store(config: dict, root: Path | None = None) -> sqlite3.Connection`, `get_stored_mtime(conn, file: str) -> float | None`, `replace_file_rows(conn, file: str, mtime: float, locations: list[CodeLocation]) -> None`, `delete_file_rows(conn, file: str) -> None`, `query_symbol(conn, symbol: str, kind: str | None = None) -> list[CodeLocation]`, `indexed_files(conn) -> set[str]` — Task 4's `query_code_index` calls all of these.

- [ ] **Step 1: Write the failing tests**

`core/tests/index/test_store.py`:

```python
from core.index.models import CodeLocation
from core.index.store import (
    delete_file_rows,
    get_stored_mtime,
    indexed_files,
    open_store,
    query_symbol,
    replace_file_rows,
)


def _config(tmp_path):
    return {"index": {"db_path": str(tmp_path / "code_index.sqlite3")}}


def test_get_stored_mtime_is_none_when_never_indexed(tmp_path):
    conn = open_store(_config(tmp_path), root=tmp_path)
    assert get_stored_mtime(conn, "a.py") is None


def test_replace_file_rows_then_query_roundtrips(tmp_path):
    conn = open_store(_config(tmp_path), root=tmp_path)
    locs = [CodeLocation(file="a.py", line=1, symbol="foo", kind="function")]
    replace_file_rows(conn, "a.py", 123.0, locs)

    assert get_stored_mtime(conn, "a.py") == 123.0
    results = query_symbol(conn, "foo")
    assert len(results) == 1
    assert results[0].symbol == "foo"
    assert results[0].file == "a.py"


def test_replace_file_rows_drops_old_rows_for_that_file(tmp_path):
    conn = open_store(_config(tmp_path), root=tmp_path)
    replace_file_rows(conn, "a.py", 1.0, [CodeLocation(file="a.py", line=1, symbol="old", kind="function")])
    replace_file_rows(conn, "a.py", 2.0, [CodeLocation(file="a.py", line=5, symbol="new", kind="function")])

    assert query_symbol(conn, "old") == []
    assert len(query_symbol(conn, "new")) == 1
    assert get_stored_mtime(conn, "a.py") == 2.0


def test_delete_file_rows_removes_everything_for_that_file(tmp_path):
    conn = open_store(_config(tmp_path), root=tmp_path)
    replace_file_rows(conn, "a.py", 1.0, [CodeLocation(file="a.py", line=1, symbol="foo", kind="function")])
    delete_file_rows(conn, "a.py")

    assert query_symbol(conn, "foo") == []
    assert get_stored_mtime(conn, "a.py") is None


def test_query_symbol_ranks_exact_match_before_substring(tmp_path):
    conn = open_store(_config(tmp_path), root=tmp_path)
    replace_file_rows(
        conn,
        "a.py",
        1.0,
        [
            CodeLocation(file="a.py", line=1, symbol="foo_helper", kind="function"),
            CodeLocation(file="a.py", line=5, symbol="foo", kind="function"),
        ],
    )
    results = query_symbol(conn, "foo")
    assert [r.symbol for r in results] == ["foo", "foo_helper"]


def test_query_symbol_filters_by_kind(tmp_path):
    conn = open_store(_config(tmp_path), root=tmp_path)
    replace_file_rows(
        conn,
        "a.py",
        1.0,
        [
            CodeLocation(file="a.py", line=1, symbol="Foo", kind="class"),
            CodeLocation(file="a.py", line=5, symbol="Foo", kind="function"),
        ],
    )
    results = query_symbol(conn, "Foo", kind="class")
    assert len(results) == 1
    assert results[0].kind == "class"


def test_indexed_files_lists_every_file_with_rows(tmp_path):
    conn = open_store(_config(tmp_path), root=tmp_path)
    replace_file_rows(conn, "a.py", 1.0, [CodeLocation(file="a.py", line=1, symbol="foo", kind="function")])
    replace_file_rows(conn, "b.py", 1.0, [])  # a file that parsed but defined nothing
    assert indexed_files(conn) == {"a.py", "b.py"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest core/tests/index/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.index.store'`

- [ ] **Step 3: Implement `store.py`**

```python
# core/index/store.py
"""SQLite-backed symbol table for the code index. A file's rows are
always replaced as a unit (delete-then-insert inside one transaction) —
there is no partial-update path, so a file's stored rows are always
consistent with the mtime that produced them.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from core.config.resolve import resolve_path
from core.index.models import CodeLocation

_SCHEMA = """
CREATE TABLE IF NOT EXISTS code_index (
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,
    file TEXT NOT NULL,
    line INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS indexed_file_mtimes (
    file TEXT PRIMARY KEY,
    mtime REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_code_index_symbol ON code_index(symbol);
CREATE INDEX IF NOT EXISTS idx_code_index_file ON code_index(file);
"""


def open_store(config: dict[str, Any], root: Path | None = None) -> sqlite3.Connection:
    db_path = resolve_path(config, "index.db_path", ".promptwise/code_index.sqlite3", root=root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def get_stored_mtime(conn: sqlite3.Connection, file: str) -> float | None:
    row = conn.execute("SELECT mtime FROM indexed_file_mtimes WHERE file = ?", (file,)).fetchone()
    return row[0] if row is not None else None


def replace_file_rows(conn: sqlite3.Connection, file: str, mtime: float, locations: list[CodeLocation]) -> None:
    with conn:
        conn.execute("DELETE FROM code_index WHERE file = ?", (file,))
        conn.executemany(
            "INSERT INTO code_index (symbol, kind, file, line) VALUES (?, ?, ?, ?)",
            [(loc.symbol, loc.kind, loc.file, loc.line) for loc in locations],
        )
        conn.execute(
            "INSERT INTO indexed_file_mtimes (file, mtime) VALUES (?, ?) "
            "ON CONFLICT(file) DO UPDATE SET mtime = excluded.mtime",
            (file, mtime),
        )


def delete_file_rows(conn: sqlite3.Connection, file: str) -> None:
    with conn:
        conn.execute("DELETE FROM code_index WHERE file = ?", (file,))
        conn.execute("DELETE FROM indexed_file_mtimes WHERE file = ?", (file,))


def query_symbol(conn: sqlite3.Connection, symbol: str, kind: str | None = None) -> list[CodeLocation]:
    sql = "SELECT symbol, kind, file, line FROM code_index WHERE symbol LIKE ?"
    params: list[Any] = [f"%{symbol}%"]
    if kind is not None:
        sql += " AND kind = ?"
        params.append(kind)
    # exact match first, then substring, both alphabetical by file for a stable order
    sql += " ORDER BY (symbol != ?) ASC, file ASC, line ASC"
    params.append(symbol)

    rows = conn.execute(sql, params).fetchall()
    return [CodeLocation(symbol=s, kind=k, file=f, line=l) for s, k, f, l in rows]


def indexed_files(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT file FROM indexed_file_mtimes").fetchall()
    return {row[0] for row in rows}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest core/tests/index/test_store.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 5: Commit**

```bash
git add core/index/store.py core/tests/index/test_store.py
git commit -m "feat(index): SQLite-backed symbol store with mtime invalidation"
```

---

### Task 4: `query_code_index` — the public verb, walk + reindex + query

**Files:**
- Create: `core/index/query.py`
- Test: `core/tests/index/test_query.py`

**Interfaces:**
- Consumes: `parse_file` (Task 1/2), `open_store`/`get_stored_mtime`/`replace_file_rows`/`delete_file_rows`/`query_symbol`/`indexed_files` (Task 3), `LANGUAGES` (Task 1/2 — for the extension-filter during the walk), `resolve_config_auto` (existing, `core/config/resolve.py`).
- Produces: `query_code_index(symbol: str, kind: str | None = None, root: Path | None = None, config: dict | None = None) -> list[CodeLocation]` — the public verb this whole sub-project exists to ship.

- [ ] **Step 1: Write the failing tests**

`core/tests/index/test_query.py`:

```python
from pathlib import Path

from core.index.query import query_code_index


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_query_code_index_finds_definitions_across_multiple_files_and_languages(tmp_path):
    _write(tmp_path / "pkg" / "a.py", "def alpha():\n    pass\n")
    _write(tmp_path / "pkg" / "b.py", "class Beta:\n    def gamma(self):\n        pass\n")
    _write(tmp_path / "web" / "c.ts", "function delta() { return 1; }\n")

    assert [loc.symbol for loc in query_code_index("alpha", root=tmp_path)] == ["alpha"]
    beta_results = query_code_index("Beta", root=tmp_path)
    assert len(beta_results) == 1
    assert beta_results[0].kind == "class"
    assert query_code_index("gamma", root=tmp_path)[0].line == 2
    assert query_code_index("delta", root=tmp_path)[0].file == str(tmp_path / "web" / "c.ts")


def test_query_code_index_on_missing_root_returns_empty(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert query_code_index("anything", root=missing) == []


def test_query_code_index_symbol_not_found_returns_empty(tmp_path):
    _write(tmp_path / "a.py", "def alpha():\n    pass\n")
    assert query_code_index("nonexistent_symbol", root=tmp_path) == []


def test_query_code_index_survives_a_syntax_error_in_one_file(tmp_path):
    _write(tmp_path / "good.py", "def alpha():\n    pass\n")
    _write(tmp_path / "bad.py", "def broken(:\n")

    results = query_code_index("alpha", root=tmp_path)
    assert len(results) == 1
    assert results[0].symbol == "alpha"


def test_query_code_index_picks_up_an_edit_via_mtime_invalidation(tmp_path):
    target = tmp_path / "a.py"
    _write(target, "def old_name():\n    pass\n")
    query_code_index("old_name", root=tmp_path)  # first index

    import time

    time.sleep(0.01)  # ensure the mtime actually advances on fast filesystems
    _write(target, "def new_name():\n    pass\n")

    assert query_code_index("old_name", root=tmp_path) == []
    assert len(query_code_index("new_name", root=tmp_path)) == 1


def test_query_code_index_drops_rows_for_a_deleted_file(tmp_path):
    target = tmp_path / "a.py"
    _write(target, "def alpha():\n    pass\n")
    query_code_index("alpha", root=tmp_path)  # first index

    target.unlink()
    assert query_code_index("alpha", root=tmp_path) == []


def test_query_code_index_skips_ignored_directories(tmp_path):
    _write(tmp_path / "real.py", "def alpha():\n    pass\n")
    _write(tmp_path / "node_modules" / "vendored.py", "def alpha():\n    pass\n")
    _write(tmp_path / ".git" / "hooks.py", "def alpha():\n    pass\n")

    results = query_code_index("alpha", root=tmp_path)
    assert len(results) == 1
    assert results[0].file == str(tmp_path / "real.py")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest core/tests/index/test_query.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.index.query'`

- [ ] **Step 3: Implement `query.py`**

```python
# core/index/query.py
"""query_code_index — the public verb. Ties the walk/reindex/query steps
together: re-parses only files that changed since the last call (by
mtime), drops rows for files no longer on disk, then answers the query
against the now-current SQLite table.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.config.resolve import resolve_config_auto
from core.index.languages import LANGUAGES
from core.index.models import CodeLocation
from core.index.parser import parse_file
from core.index.store import (
    delete_file_rows,
    get_stored_mtime,
    indexed_files,
    open_store,
    query_symbol,
    replace_file_rows,
)

_IGNORED_DIR_NAMES = {".git", "node_modules", "__pycache__", ".venv", "venv"}


def _iter_source_files(root: Path):
    for path in root.rglob("*"):
        if path.suffix not in LANGUAGES:
            continue
        if any(part in _IGNORED_DIR_NAMES or (part.startswith(".") and part != ".") for part in path.relative_to(root).parts[:-1]):
            continue
        if path.is_file():
            yield path


def query_code_index(
    symbol: str,
    kind: str | None = None,
    root: Path | None = None,
    config: dict[str, Any] | None = None,
) -> list[CodeLocation]:
    root = root if root is not None else Path.cwd()
    if not root.exists():
        return []

    config = config if config is not None else resolve_config_auto(root=root)
    conn = open_store(config, root=root)

    seen_files: set[str] = set()
    for path in _iter_source_files(root):
        file_key = str(path)
        seen_files.add(file_key)
        try:
            current_mtime = path.stat().st_mtime
        except FileNotFoundError:
            continue  # vanished between the walk and the stat() call — treat as not present

        if get_stored_mtime(conn, file_key) == current_mtime:
            continue  # unchanged since last index

        locations = parse_file(path)
        replace_file_rows(conn, file_key, current_mtime, locations)

    for stale_file in indexed_files(conn) - seen_files:
        delete_file_rows(conn, stale_file)

    return query_symbol(conn, symbol, kind)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest core/tests/index/test_query.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 5: Run the full index test suite together**

Run: `pytest core/tests/index -v`
Expected: PASS (all tests across test_parser.py, test_store.py, test_query.py)

- [ ] **Step 6: Run the full project test suite to confirm no regressions**

Run: `pytest core/tests gateway/tests scripts/tests -q`
Expected: PASS, count increased by this task's new tests, no prior test broken

- [ ] **Step 7: Commit**

```bash
git add core/index/query.py core/tests/index/test_query.py
git commit -m "feat(index): query_code_index — the public verb, walk + reindex + query"
```

---

## Post-plan follow-ups (not part of this plan, log to `docs/BACKLOG.md` if not picked up immediately)

- MCP tool exposure for `query_code_index` (mirrors `gateway/mcp_server.py`'s `verify_output` wrapper) — small, separate task once this verb is stable.
- Reference-finding ("what calls Y") — natural extension of the same store, needs its own query captures (call-site nodes, not definition nodes) and its own spec section if picked up.
- The memory/fact layer sub-project (hybrid BM25+vector retrieval, PII exclusion) is a separate, later spec — this plan does not block it, but shares no code with it (deliberately, per the design spec's Decision 2).
