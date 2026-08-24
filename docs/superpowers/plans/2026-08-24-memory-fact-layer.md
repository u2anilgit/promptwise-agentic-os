# Memory & Fact Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `record_memory`/`query_memory` — on-demand fact extraction, hybrid BM25+vector storage, and relevance-ranked retrieval, as `core/memory/`.

**Architecture:** File-per-concern under `core/memory/` (models/store/embed/extract/vectors/rank/memory), mirroring `core/index/`'s convention. SQLite FTS5 for lexical (BM25) search, Qdrant for vectors, Ollama over plain HTTP (stdlib `urllib`, no new HTTP dependency) for both embeddings and fact-extraction generation, `route_request` used only for *tier/model selection* (it does not itself call a model — verified against `core/routing/router.py`, there is no LLM-invocation code anywhere in this repo today). Reciprocal Rank Fusion merges the two result lists.

**Tech Stack:** Python 3.12 (repo's declared floor — dev machine runs 3.11.5, a pre-existing gap, not this plan's to fix), SQLite (`sqlite3` stdlib, FTS5 confirmed available: `sqlite3.sqlite_version` 3.42.0 on this machine), `qdrant-client` (new dependency, verified installed at 1.19.0 during plan authoring — API surface below is hand-verified against that real install, not guessed), Pydantic v2, stdlib `urllib.request` for Ollama HTTP calls (matches the one existing HTTP-call precedent in this repo, `core/diagnostics/checks.py`'s `_check_services_gateway`).

**Spec:** `docs/superpowers/specs/2026-08-24-memory-fact-layer-design.md`

## Global Constraints

- Core stays language/domain-agnostic — no pack-specific branching in `core/memory/`.
- No verb reads a config file directly — always through `core/config/resolve.py` (`resolve_config_auto(root=...)`, `resolve_path(config, key, default, root=...)`).
- `resolve_config_auto(root=<target root>)`, never process cwd (Phase-2's own bug class — do not reintroduce).
- Pydantic v2 `BaseModel` subclasses for the typed contract (`Fact`), same flat-field/`Literal[...]` style as `core/index/models.py`'s `CodeLocation`.
- Every verb call is auditable via `record_audit` at the boundary, one call site per verb, not scattered (`core/CLAUDE.md`'s convention; exact signature verified below).
- Never crash on malformed input: unreachable Ollama, unreachable Qdrant, a non-directory `root`, empty/whitespace-only `text` are all handled states, not exceptions — this was a real, twice-found bug class in the code-index sub-project's two review rounds; design it in from Task 1 here.
- TDD (`superpowers:test-driven-development`): failing test before implementation, every task.
- Dependency injection for network calls, not monkeypatching — `core/tests/routing/test_router.py` establishes this repo's actual testing convention (every `route_request` test passes real objects via keyword args, zero uses of `unittest.mock`/`responses`/`respx` anywhere in `core/tests/`). Every function in this plan that makes a network call takes an injectable callable/client parameter with a real default, so tests inject a fake instead of patching internals.

## Verified interfaces this plan depends on (hand-checked against the real source, not assumed)

```python
# core/routing/router.py — route_request does NOT call a model. It only picks
# which tier/model_id a caller SHOULD use. hardware=None and catalog=None both
# auto-resolve internally (detect_hardware(), load_catalog(config)) — safe to
# omit both in every call site below.
class RouteRequest(BaseModel):
    task_type: str = "general"
    privacy_sensitive: bool = False
    preferred_tier: str | None = None

class RoutingDecision(BaseModel):
    tier: str
    provider: str
    model_id: str
    reason: str
    fallback_applied: bool
    privacy_forced: bool = False

def route_request(
    request: RouteRequest,
    hardware: HardwareProfile | None = None,
    config: dict | None = None,
    catalog: dict[str, ModelTier] | None = None,
) -> RoutingDecision: ...

# core/config/resolve.py
def resolve_config_auto(root: Path | None = None, env: Mapping[str, str] | None = None) -> dict[str, Any]: ...
def resolve_path(config: dict[str, Any], config_key: str, default_relpath: str, root: Path | None = None) -> Path: ...

# core/audit/log.py
def record_audit(
    config: dict[str, Any], actor: str, action: str, target: str, result: str,
    detail: dict[str, Any] | None = None,
) -> AuditRecord: ...
# real call-site convention (core/actions/fs.py): result is the literal string "allow"/"deny" there;
# this plan uses "success"/"error" for memory's own actions, since there's no allow/deny decision here.

# qdrant-client 1.19.0 (verified live against a :memory: instance during plan authoring)
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct, Filter, FieldCondition, MatchValue
client = QdrantClient(":memory:")               # tests/dev — no Docker needed
client.collection_exists("name") -> bool
client.create_collection("name", vectors_config=VectorParams(size=768, distance=Distance.COSINE))
client.upsert("name", points=[PointStruct(id=1, vector=[...], payload={...})])
client.query_points("name", query=[...], query_filter=Filter(must=[FieldCondition(key="scope", match=MatchValue(value="project"))]), limit=10)
# -> QueryResponse(points=[ScoredPoint(id=1, score=0.999..., payload={...}, ...), ...])
# NOTE: client.search() is REMOVED in this version — query_points is the only search method. Do not use .search().

# sqlite3 (stdlib, 3.42.0 on this machine) — FTS5 confirmed working, bm25() confirmed working.
# IMPORTANT: bm25()'s score is NEGATIVE and LOWER (more negative) means MORE relevant —
# order ASC, not DESC. Verified live: a matching row scored -9.24e-07, ordered first with ASC.
```

---

### Task 1: `Fact` model, `qdrant-client` dependency, `memory` config block

**Files:**
- Create: `core/memory/__init__.py` (empty)
- Create: `core/memory/models.py`
- Modify: `pyproject.toml` (add `qdrant-client` to `[project].dependencies`)
- Modify: `core/config/defaults.yaml` (add `memory:` block)
- Test: `core/tests/memory/__init__.py` (empty), `core/tests/memory/test_models.py`

**Interfaces:**
- Produces: `Fact` (Pydantic v2 model) — every later task imports this.

- [ ] **Step 1: Write the failing test**

`core/tests/memory/test_models.py`:
```python
from core.memory.models import Fact


def test_fact_requires_all_non_defaulted_fields():
    fact = Fact(text="user prefers pytest", category="preference", scope="project", root="/repo", created_at=1000.0)
    assert fact.text == "user prefers pytest"
    assert fact.category == "preference"
    assert fact.scope == "project"
    assert fact.root == "/repo"
    assert fact.created_at == 1000.0
    assert fact.id is None          # not yet persisted
    assert fact.session_id is None  # scope="project", no session
    assert fact.pii is False        # default


def test_fact_session_scope_takes_session_id_not_root():
    fact = Fact(text="working on the login bug", category="context", scope="session", session_id="abc123", created_at=1000.0)
    assert fact.scope == "session"
    assert fact.session_id == "abc123"
    assert fact.root is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/memory/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.memory'`

- [ ] **Step 3: Implement `models.py`**

```python
# core/memory/models.py
from typing import Literal

from pydantic import BaseModel


class Fact(BaseModel):
    id: int | None = None
    text: str
    category: str
    scope: Literal["session", "project"]
    root: str | None = None
    session_id: str | None = None
    pii: bool = False
    created_at: float
```

- [ ] **Step 4: Add `core/memory/__init__.py` and `core/tests/memory/__init__.py`** (both empty files, same as `core/index/__init__.py`/`core/tests/index/__init__.py`)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest core/tests/memory/test_models.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Add the `qdrant-client` dependency**

In `pyproject.toml`, add to the existing `dependencies` list (after `"tree-sitter-javascript>=0.25"`):
```toml
    "qdrant-client>=1.19,<2",
```

- [ ] **Step 7: Add the `memory` config block**

In `core/config/defaults.yaml`, add a new top-level block (after the existing `audit:` block, before `verify:`):
```yaml
memory:
  db_path: .promptwise/memory.sqlite3
  qdrant_url: http://127.0.0.1:6333
  ollama_base_url: http://127.0.0.1:11434
  embedding_model: nomic-embed-text
  embedding_dim: 768
  extraction_tier_hint: local-small
```

- [ ] **Step 8: Install the new dependency locally so later tasks' tests can import it**

Run: `python -m pip install -e .` (or `python -m pip install "qdrant-client>=1.19,<2"` directly if the editable install doesn't pick up the pyproject change immediately)
Expected: `qdrant_client` importable — `python -c "import qdrant_client"` exits 0.

- [ ] **Step 9: Commit**

```bash
git add core/memory/__init__.py core/memory/models.py core/tests/memory/__init__.py core/tests/memory/test_models.py pyproject.toml core/config/defaults.yaml
git commit -m "feat(memory): Fact model, qdrant-client dependency, memory config block"
```

---

### Task 2: `core/memory/store.py` — SQLite fact storage + FTS5 BM25 search

**Files:**
- Create: `core/memory/store.py`
- Test: `core/tests/memory/test_store.py`

**Interfaces:**
- Consumes: `Fact` (Task 1), `resolve_path` (`core/config/resolve.py`, verified signature above).
- Produces: `open_store(config, root=None) -> sqlite3.Connection`, `save_fact(conn, fact: Fact) -> Fact` (returns the fact with `.id` populated), `search_fts(conn, query: str, scope: str, root: str | None = None, limit: int = 10) -> list[Fact]` — consumed by Task 8.

- [ ] **Step 1: Write the failing tests**

`core/tests/memory/test_store.py`:
```python
import time

from core.memory.models import Fact
from core.memory.store import open_store, save_fact, search_fts


def _config(tmp_path):
    return {"memory": {"db_path": str(tmp_path / "memory.sqlite3")}}


def test_save_fact_assigns_an_id(tmp_path):
    conn = open_store(_config(tmp_path))
    fact = Fact(text="user prefers pytest", category="preference", scope="project", root="/repo", created_at=time.time())
    saved = save_fact(conn, fact)
    assert saved.id is not None


def test_search_fts_finds_a_saved_fact_by_lexical_match(tmp_path):
    conn = open_store(_config(tmp_path))
    save_fact(conn, Fact(text="user prefers pytest over unittest", category="preference", scope="project", root="/repo", created_at=time.time()))
    save_fact(conn, Fact(text="decided: SQLite for dev, Postgres for prod", category="decision", scope="project", root="/repo", created_at=time.time()))

    results = search_fts(conn, "pytest", scope="project", root="/repo")
    assert len(results) == 1
    assert "pytest" in results[0].text


def test_search_fts_scopes_by_root(tmp_path):
    conn = open_store(_config(tmp_path))
    save_fact(conn, Fact(text="alpha decision", category="decision", scope="project", root="/repo-a", created_at=time.time()))
    save_fact(conn, Fact(text="alpha decision elsewhere", category="decision", scope="project", root="/repo-b", created_at=time.time()))

    results = search_fts(conn, "alpha", scope="project", root="/repo-a")
    assert len(results) == 1
    assert results[0].root == "/repo-a"


def test_search_fts_scopes_by_session_not_root(tmp_path):
    conn = open_store(_config(tmp_path))
    save_fact(conn, Fact(text="working the login bug", category="context", scope="session", session_id="s1", created_at=time.time()))
    save_fact(conn, Fact(text="working the login bug elsewhere", category="context", scope="session", session_id="s2", created_at=time.time()))

    results = search_fts(conn, "login", scope="session", root=None)
    assert len(results) == 2  # session scope isn't root-filtered; caller filters by session_id itself if needed


def test_search_fts_no_match_returns_empty(tmp_path):
    conn = open_store(_config(tmp_path))
    save_fact(conn, Fact(text="user prefers pytest", category="preference", scope="project", root="/repo", created_at=time.time()))
    assert search_fts(conn, "nonexistent_term_xyz", scope="project", root="/repo") == []


def test_search_fts_respects_limit(tmp_path):
    conn = open_store(_config(tmp_path))
    for i in range(5):
        save_fact(conn, Fact(text=f"fact number {i} about testing", category="context", scope="project", root="/repo", created_at=time.time()))
    assert len(search_fts(conn, "testing", scope="project", root="/repo", limit=3)) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/memory/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.memory.store'`

- [ ] **Step 3: Implement `store.py`**

```python
# core/memory/store.py
"""SQLite-backed fact storage with FTS5 lexical (BM25) search. External-
content FTS5 table (content='facts', content_rowid='id') — no built-in
sync triggers, so save_fact writes both tables in one transaction.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from core.config.resolve import resolve_path
from core.memory.models import Fact

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    category TEXT NOT NULL,
    scope TEXT NOT NULL,
    root TEXT,
    session_id TEXT,
    pii INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(text, content='facts', content_rowid='id');
CREATE INDEX IF NOT EXISTS idx_facts_scope_root ON facts(scope, root);
CREATE INDEX IF NOT EXISTS idx_facts_scope_session ON facts(scope, session_id);
"""


def open_store(config: dict[str, Any], root: Path | None = None) -> sqlite3.Connection:
    db_path = resolve_path(config, "memory.db_path", ".promptwise/memory.sqlite3", root=root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)  # same busy-timeout convention as core/index/store.py
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def save_fact(conn: sqlite3.Connection, fact: Fact) -> Fact:
    with conn:
        cursor = conn.execute(
            "INSERT INTO facts (text, category, scope, root, session_id, pii, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (fact.text, fact.category, fact.scope, fact.root, fact.session_id, int(fact.pii), fact.created_at),
        )
        fact_id = cursor.lastrowid
        conn.execute("INSERT INTO facts_fts (rowid, text) VALUES (?, ?)", (fact_id, fact.text))
    return fact.model_copy(update={"id": fact_id})


def _sanitize_fts_query(query: str) -> str:
    # FTS5's query syntax treats punctuation specially (AND/OR/NOT, quotes,
    # NEAR, column filters, etc.). A raw user string could be malformed
    # syntax rather than a search term — extract word tokens and OR them,
    # same "treat untrusted input as a handled state" convention as the
    # rest of this repo, not a security fix (parameters are still bound).
    tokens = re.findall(r"\w+", query)
    if not tokens:
        return ""
    return " OR ".join(tokens)


def search_fts(
    conn: sqlite3.Connection,
    query: str,
    scope: str,
    root: str | None = None,
    limit: int = 10,
) -> list[Fact]:
    fts_query = _sanitize_fts_query(query)
    if not fts_query:
        return []

    sql = (
        "SELECT f.id, f.text, f.category, f.scope, f.root, f.session_id, f.pii, f.created_at "
        "FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid "
        "WHERE facts_fts MATCH ? AND f.scope = ?"
    )
    params: list[Any] = [fts_query, scope]
    if root is not None:
        sql += " AND f.root = ?"
        params.append(root)
    # bm25()'s score is negative; more negative = more relevant. ASC puts
    # the best match first (verified live against a real FTS5 table).
    sql += " ORDER BY bm25(facts_fts) ASC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [
        Fact(id=r[0], text=r[1], category=r[2], scope=r[3], root=r[4], session_id=r[5], pii=bool(r[6]), created_at=r[7])
        for r in rows
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests/memory/test_store.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add core/memory/store.py core/tests/memory/test_store.py
git commit -m "feat(memory): SQLite fact store with FTS5 BM25 search"
```

---

### Task 3: PII detection — extend `core/diagnostics/redact.py`

**Files:**
- Modify: `core/diagnostics/redact.py`
- Test: `core/tests/diagnostics/test_redact.py` (create if it doesn't exist yet — check first; if it exists, add to it instead of overwriting)

**Interfaces:**
- Produces: `contains_pii(text: str) -> bool` — consumed by Task 8.

- [ ] **Step 1: Check whether `core/tests/diagnostics/test_redact.py` already exists**

Run: `python -c "import pathlib; print(pathlib.Path('core/tests/diagnostics/test_redact.py').exists())"`
If `True`: read the existing file first and add the new tests below to it (don't overwrite existing `redact_secrets` tests). If `False`: create it fresh with just the new tests below (do NOT invent `redact_secrets` tests that don't already exist — Task 3 only owns `contains_pii`).

- [ ] **Step 2: Write the failing tests**

Add to `core/tests/diagnostics/test_redact.py`:
```python
from core.diagnostics.redact import contains_pii


def test_contains_pii_detects_an_email_address():
    assert contains_pii("contact me at jane.doe@example.com") is True


def test_contains_pii_detects_a_phone_number():
    assert contains_pii("call 555-123-4567 for details") is True


def test_contains_pii_detects_an_existing_secret_pattern():
    assert contains_pii("api_key: sk-ant-abcdefghijklmnopqrstuvwx") is True


def test_contains_pii_false_for_ordinary_text():
    assert contains_pii("user prefers pytest over unittest") is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest core/tests/diagnostics/test_redact.py -v -k contains_pii`
Expected: FAIL — `ImportError: cannot import name 'contains_pii'`

- [ ] **Step 4: Implement `contains_pii`**

In `core/diagnostics/redact.py`, add an email/phone pattern list and the new function (keep the existing `_PATTERNS`/`redact_secrets` untouched):

```python
_PII_PATTERNS = [
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),          # email
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),  # US-style phone
]


def contains_pii(text: str) -> bool:
    """Detection only — never mutates the input. A flagged fact still
    stores its full text locally; the flag only gates cloud-bound
    context assembly (docs/superpowers/specs/2026-08-24-memory-fact-layer-design.md,
    Decision 4)."""
    for pattern in _PATTERNS + _PII_PATTERNS:
        if pattern.search(text):
            return True
    return False
```

Update the module docstring's second sentence to mention both uses:
```python
"""Shared redaction utility — docs/MAINTENANCE.md §3: "one implementation,
not two." Used by the support bundle (redact_secrets) and the memory
layer's PII flagging (contains_pii, docs/superpowers/specs/2026-08-24-memory-fact-layer-design.md).
Pattern-based, not exhaustive — covers common secret shapes (API keys,
bearer tokens, password assignments) and common PII shapes (email,
phone); redacted before write, never after, per the same section.
"""
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest core/tests/diagnostics/test_redact.py -v`
Expected: PASS (all tests in the file, old and new)

- [ ] **Step 6: Commit**

```bash
git add core/diagnostics/redact.py core/tests/diagnostics/test_redact.py
git commit -m "feat(diagnostics): contains_pii detector — email/phone patterns for the memory layer"
```

---

### Task 4: `core/memory/embed.py` — Ollama embeddings over HTTP

**Files:**
- Create: `core/memory/embed.py`
- Test: `core/tests/memory/test_embed.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (standalone HTTP client).
- Produces: `HttpPost` type alias, `default_http_post(url, json_body, timeout=10.0) -> dict`, `embed_text(text: str, config: dict, http_post: HttpPost = default_http_post) -> list[float] | None` — consumed by Task 8. Returns `None` (not an exception) when the call fails.

- [ ] **Step 1: Write the failing tests**

`core/tests/memory/test_embed.py`:
```python
import pytest

from core.memory.embed import embed_text


def _config():
    return {"memory": {"ollama_base_url": "http://127.0.0.1:11434", "embedding_model": "nomic-embed-text"}}


def test_embed_text_returns_the_embedding_on_success():
    def fake_http_post(url, json_body, timeout=10.0):
        assert url == "http://127.0.0.1:11434/api/embeddings"
        assert json_body == {"model": "nomic-embed-text", "prompt": "user prefers pytest"}
        return {"embedding": [0.1, 0.2, 0.3]}

    result = embed_text("user prefers pytest", _config(), http_post=fake_http_post)
    assert result == [0.1, 0.2, 0.3]


def test_embed_text_returns_none_when_the_request_fails():
    def failing_http_post(url, json_body, timeout=10.0):
        raise OSError("connection refused")

    assert embed_text("anything", _config(), http_post=failing_http_post) is None


def test_embed_text_returns_none_on_a_malformed_response():
    def malformed_http_post(url, json_body, timeout=10.0):
        return {"unexpected": "shape"}

    assert embed_text("anything", _config(), http_post=malformed_http_post) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/memory/test_embed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.memory.embed'`

- [ ] **Step 3: Implement `embed.py`**

```python
# core/memory/embed.py
"""Ollama embeddings over plain HTTP. stdlib urllib, no new HTTP
dependency — matches this repo's one existing HTTP-call precedent
(core/diagnostics/checks.py's _check_services_gateway). Unreachable
Ollama, a timeout, or a malformed response are handled states — this
function returns None, never raises, so a caller can degrade to
BM25-only retrieval instead of aborting.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable

HttpPost = Callable[..., dict[str, Any]]


def default_http_post(url: str, json_body: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    data = json.dumps(json_body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310 — local-only, fixed scheme
        return json.loads(response.read().decode("utf-8"))


def embed_text(text: str, config: dict[str, Any], http_post: HttpPost = default_http_post) -> list[float] | None:
    memory_config = config.get("memory", {})
    base_url = memory_config.get("ollama_base_url", "http://127.0.0.1:11434")
    model = memory_config.get("embedding_model", "nomic-embed-text")

    try:
        body = http_post(f"{base_url}/api/embeddings", {"model": model, "prompt": text})
    except (OSError, urllib.error.URLError, TimeoutError):
        return None

    embedding = body.get("embedding")
    if not isinstance(embedding, list):
        return None
    return embedding
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests/memory/test_embed.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add core/memory/embed.py core/tests/memory/test_embed.py
git commit -m "feat(memory): embed_text — Ollama embeddings over HTTP, degrade-not-raise on failure"
```

---

### Task 5: `core/memory/extract.py` — fact extraction

**Files:**
- Create: `core/memory/extract.py`
- Test: `core/tests/memory/test_extract.py`

**Interfaces:**
- Consumes: `RouteRequest`, `route_request` (`core/routing/router.py`, verified signature above), `HttpPost`/`default_http_post` (Task 4).
- Produces: `extract_facts(text: str, config: dict, http_post: HttpPost = default_http_post) -> list[dict]` — each dict is `{"text": str, "category": str}`. Consumed by Task 8. Never raises; falls back to a single unclassified fact on any failure. Empty/whitespace input returns `[]`.

- [ ] **Step 1: Write the failing tests**

`core/tests/memory/test_extract.py`:
```python
from core.memory.extract import extract_facts


def _config():
    return {
        "engine": {"local_only": True},
        "routing": {"default_tier": "local-small"},
        "memory": {"ollama_base_url": "http://127.0.0.1:11434", "extraction_tier_hint": "local-small"},
    }


def test_extract_facts_parses_a_valid_json_response():
    def fake_http_post(url, json_body, timeout=10.0):
        assert url.endswith("/api/generate")
        return {"response": '{"facts": [{"text": "user prefers pytest", "category": "preference"}]}'}

    facts = extract_facts("I always use pytest, never unittest", _config(), http_post=fake_http_post)
    assert facts == [{"text": "user prefers pytest", "category": "preference"}]


def test_extract_facts_falls_back_to_one_unclassified_fact_on_unreachable_ollama():
    def failing_http_post(url, json_body, timeout=10.0):
        raise OSError("connection refused")

    facts = extract_facts("some raw session text", _config(), http_post=failing_http_post)
    assert facts == [{"text": "some raw session text", "category": "unclassified"}]


def test_extract_facts_falls_back_to_one_unclassified_fact_on_invalid_json():
    def bad_json_http_post(url, json_body, timeout=10.0):
        return {"response": "not valid json at all"}

    facts = extract_facts("some raw session text", _config(), http_post=bad_json_http_post)
    assert facts == [{"text": "some raw session text", "category": "unclassified"}]


def test_extract_facts_empty_text_returns_empty_list():
    assert extract_facts("   ", _config()) == []
    assert extract_facts("", _config()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/memory/test_extract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.memory.extract'`

- [ ] **Step 3: Implement `extract.py`**

```python
# core/memory/extract.py
"""Fact/decision extraction via a local model. route_request only picks
WHICH model to use (tier -> model_id); the actual generation call is
plain HTTP against Ollama's /api/generate, same handled-state-not-
exception convention as embed.py. An unreachable Ollama or a response
that isn't valid {"facts": [...]} JSON both fall back to treating the
whole input as one unclassified fact — never raises.
"""
from __future__ import annotations

import json
from typing import Any

from core.memory.embed import HttpPost, default_http_post
from core.routing.router import RouteRequest, route_request

_EXTRACTION_PROMPT = """Extract distinct facts, decisions, or stated \
preferences from the text below as JSON: {{"facts": [{{"text": "...", \
"category": "preference|decision|context"}}]}}. One idea per fact, \
concise. Respond with ONLY the JSON object, no other text.

Text:
{text}
"""


def extract_facts(text: str, config: dict[str, Any], http_post: HttpPost = default_http_post) -> list[dict[str, str]]:
    if not text.strip():
        return []

    memory_config = config.get("memory", {})
    base_url = memory_config.get("ollama_base_url", "http://127.0.0.1:11434")
    tier_hint = memory_config.get("extraction_tier_hint", "local-small")

    decision = route_request(RouteRequest(task_type="fact_extraction", preferred_tier=tier_hint), config=config)

    try:
        body = http_post(
            f"{base_url}/api/generate",
            {"model": decision.model_id, "prompt": _EXTRACTION_PROMPT.format(text=text), "format": "json", "stream": False},
        )
        parsed = json.loads(body["response"])
        facts = parsed["facts"]
        if not isinstance(facts, list):
            raise ValueError("facts is not a list")
        return [{"text": str(f["text"]), "category": str(f["category"])} for f in facts]
    except Exception:
        # covers: OSError/URLError (unreachable), KeyError/TypeError (missing
        # keys), json.JSONDecodeError (invalid JSON), ValueError (wrong shape)
        # — any of these is "the model didn't cooperate", a handled state.
        return [{"text": text.strip(), "category": "unclassified"}]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests/memory/test_extract.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add core/memory/extract.py core/tests/memory/test_extract.py
git commit -m "feat(memory): extract_facts — local-model fact extraction, unclassified-fact fallback"
```

---

### Task 6: `core/memory/vectors.py` — Qdrant wrapper

**Files:**
- Create: `core/memory/vectors.py`
- Test: `core/tests/memory/test_vectors.py`

**Interfaces:**
- Consumes: `qdrant_client.QdrantClient` and `qdrant_client.models` (verified API above).
- Produces: `COLLECTION_NAME` constant, `ensure_collection(client, dim: int) -> None`, `upsert_fact(client, fact_id: int, vector: list[float], scope: str, root: str | None, pii: bool) -> None`, `search(client, query_vector: list[float], scope: str, root: str | None = None, limit: int = 20) -> list[int]` (returns fact IDs, best match first) — consumed by Task 8.

- [ ] **Step 1: Write the failing tests**

`core/tests/memory/test_vectors.py`:
```python
from qdrant_client import QdrantClient

from core.memory.vectors import ensure_collection, search, upsert_fact


def _client():
    client = QdrantClient(":memory:")
    ensure_collection(client, dim=4)
    return client


def test_ensure_collection_is_idempotent():
    client = _client()
    ensure_collection(client, dim=4)  # second call must not raise
    ensure_collection(client, dim=4)


def test_upsert_and_search_roundtrips():
    client = _client()
    upsert_fact(client, fact_id=1, vector=[1.0, 0.0, 0.0, 0.0], scope="project", root="/repo", pii=False)
    upsert_fact(client, fact_id=2, vector=[0.0, 1.0, 0.0, 0.0], scope="project", root="/repo", pii=False)

    results = search(client, query_vector=[1.0, 0.0, 0.0, 0.0], scope="project", root="/repo")
    assert results[0] == 1  # closest vector ranks first


def test_search_filters_by_scope_and_root():
    client = _client()
    upsert_fact(client, fact_id=1, vector=[1.0, 0.0, 0.0, 0.0], scope="project", root="/repo-a", pii=False)
    upsert_fact(client, fact_id=2, vector=[1.0, 0.0, 0.0, 0.0], scope="project", root="/repo-b", pii=False)

    results = search(client, query_vector=[1.0, 0.0, 0.0, 0.0], scope="project", root="/repo-a")
    assert results == [1]


def test_search_respects_limit():
    client = _client()
    for i in range(5):
        upsert_fact(client, fact_id=i, vector=[1.0, 0.0, 0.0, 0.0], scope="project", root="/repo", pii=False)
    assert len(search(client, query_vector=[1.0, 0.0, 0.0, 0.0], scope="project", root="/repo", limit=3)) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/memory/test_vectors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.memory.vectors'`

- [ ] **Step 3: Implement `vectors.py`**

```python
# core/memory/vectors.py
"""Qdrant wrapper for fact embeddings. client.query_points is the only
search method on qdrant-client 1.19 — client.search() was removed in
this version, verified live against a real install; do not reintroduce
it. Payload carries scope/root/pii so a single collection serves every
project/session rather than one collection per root (avoids collection-
count blowup as projects grow, per the design spec's storage decision).
"""
from __future__ import annotations

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

COLLECTION_NAME = "promptwise_memory"


def ensure_collection(client: QdrantClient, dim: int) -> None:
    if not client.collection_exists(COLLECTION_NAME):
        client.create_collection(COLLECTION_NAME, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))


def upsert_fact(client: QdrantClient, fact_id: int, vector: list[float], scope: str, root: str | None, pii: bool) -> None:
    client.upsert(
        COLLECTION_NAME,
        points=[PointStruct(id=fact_id, vector=vector, payload={"scope": scope, "root": root, "pii": pii})],
    )


def search(client: QdrantClient, query_vector: list[float], scope: str, root: str | None = None, limit: int = 20) -> list[int]:
    must = [FieldCondition(key="scope", match=MatchValue(value=scope))]
    if root is not None:
        must.append(FieldCondition(key="root", match=MatchValue(value=root)))

    response = client.query_points(COLLECTION_NAME, query=query_vector, query_filter=Filter(must=must), limit=limit)
    return [point.id for point in response.points]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests/memory/test_vectors.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add core/memory/vectors.py core/tests/memory/test_vectors.py
git commit -m "feat(memory): Qdrant vector store wrapper — ensure_collection, upsert_fact, search"
```

---

### Task 7: `core/memory/rank.py` — Reciprocal Rank Fusion

**Files:**
- Create: `core/memory/rank.py`
- Test: `core/tests/memory/test_rank.py`

**Interfaces:**
- Consumes: nothing (pure function, plain lists of ints).
- Produces: `reciprocal_rank_fusion(bm25_ids: list[int], vector_ids: list[int], k: int = 60) -> list[int]` — consumed by Task 8. Both inputs are already best-first; output is fused-best-first, deduplicated.

- [ ] **Step 1: Write the failing tests**

`core/tests/memory/test_rank.py`:
```python
from core.memory.rank import reciprocal_rank_fusion


def test_fusion_ranks_an_id_in_both_lists_above_one_in_a_single_list():
    # id 1: rank 1 in both lists. id 2: rank 2 in bm25 only. id 3: rank 2 in vector only.
    bm25_ids = [1, 2]
    vector_ids = [1, 3]
    fused = reciprocal_rank_fusion(bm25_ids, vector_ids)
    assert fused[0] == 1  # appears in both, highest fused score


def test_fusion_deduplicates_ids():
    fused = reciprocal_rank_fusion([1, 2, 3], [1, 2, 3])
    assert fused == [1, 2, 3]  # same relative order preserved, no duplicates


def test_fusion_handles_disjoint_lists():
    fused = reciprocal_rank_fusion([1, 2], [3, 4])
    assert set(fused) == {1, 2, 3, 4}
    assert len(fused) == 4


def test_fusion_handles_one_empty_list():
    assert reciprocal_rank_fusion([], [1, 2]) == [1, 2]
    assert reciprocal_rank_fusion([1, 2], []) == [1, 2]


def test_fusion_handles_both_empty():
    assert reciprocal_rank_fusion([], []) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/memory/test_rank.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.memory.rank'`

- [ ] **Step 3: Implement `rank.py`**

```python
# core/memory/rank.py
"""Reciprocal Rank Fusion — standard IR technique for merging two
already-ranked result lists without needing their scores to be on
comparable scales (BM25 and cosine similarity aren't). k=60 is the
literature-standard smoothing constant; there's no repo-specific reason
to deviate (design spec's open question, resolved here).
"""
from __future__ import annotations


def reciprocal_rank_fusion(bm25_ids: list[int], vector_ids: list[int], k: int = 60) -> list[int]:
    scores: dict[int, float] = {}
    for rank, fact_id in enumerate(bm25_ids, start=1):
        scores[fact_id] = scores.get(fact_id, 0.0) + 1.0 / (k + rank)
    for rank, fact_id in enumerate(vector_ids, start=1):
        scores[fact_id] = scores.get(fact_id, 0.0) + 1.0 / (k + rank)

    return sorted(scores, key=lambda fact_id: scores[fact_id], reverse=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests/memory/test_rank.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add core/memory/rank.py core/tests/memory/test_rank.py
git commit -m "feat(memory): reciprocal_rank_fusion — merge BM25 and vector result lists"
```

---

### Task 8: `core/memory/memory.py` — public verbs, wiring, audit

**Files:**
- Create: `core/memory/memory.py`
- Test: `core/tests/memory/test_memory.py`

**Interfaces:**
- Consumes: everything from Tasks 1-7 — `Fact` (models.py), `open_store`/`save_fact`/`search_fts` (store.py), `contains_pii` (redact.py), `embed_text`/`default_http_post`/`HttpPost` (embed.py), `extract_facts` (extract.py), `ensure_collection`/`upsert_fact`/`search` as `vector_search` (vectors.py), `reciprocal_rank_fusion` (rank.py), `record_audit` (`core/audit/log.py`, verified signature above), `resolve_config_auto` (`core/config/resolve.py`).
- Produces: `record_memory(text, scope, root=None, session_id=None, config=None, http_post=default_http_post, qdrant_client=None) -> list[Fact]`, `query_memory(query, scope, root=None, allow_pii=True, limit=10, config=None, http_post=default_http_post, qdrant_client=None) -> list[Fact]` — the sub-project's two public verbs.

- [ ] **Step 1: Write the failing tests**

`core/tests/memory/test_memory.py`:
```python
from qdrant_client import QdrantClient

from core.memory.memory import query_memory, record_memory


def _config(tmp_path):
    return {
        "engine": {"local_only": True},
        "routing": {"default_tier": "local-small"},
        "memory": {
            "db_path": str(tmp_path / "memory.sqlite3"),
            "embedding_model": "nomic-embed-text",
            "embedding_dim": 4,
            "extraction_tier_hint": "local-small",
        },
        "audit": {"log_path": str(tmp_path / "audit.jsonl")},
    }


def _fake_extraction_http_post(fact_text, category="preference"):
    def _post(url, json_body, timeout=10.0):
        if url.endswith("/api/generate"):
            return {"response": f'{{"facts": [{{"text": "{fact_text}", "category": "{category}"}}]}}'}
        if url.endswith("/api/embeddings"):
            return {"embedding": [0.1, 0.2, 0.3, 0.4]}
        raise AssertionError(f"unexpected url {url}")
    return _post


def test_record_memory_extracts_embeds_and_stores_a_fact(tmp_path):
    config = _config(tmp_path)
    client = QdrantClient(":memory:")

    facts = record_memory(
        "I always use pytest, never unittest", scope="project", root=str(tmp_path),
        config=config, http_post=_fake_extraction_http_post("user prefers pytest"), qdrant_client=client,
    )

    assert len(facts) == 1
    assert facts[0].text == "user prefers pytest"
    assert facts[0].id is not None


def test_query_memory_finds_a_recorded_fact_by_lexical_match(tmp_path):
    config = _config(tmp_path)
    client = QdrantClient(":memory:")
    record_memory(
        "decided: SQLite for dev, Postgres for prod", scope="project", root=str(tmp_path),
        config=config, http_post=_fake_extraction_http_post("decided: SQLite for dev, Postgres for prod", "decision"),
        qdrant_client=client,
    )

    results = query_memory(
        "SQLite", scope="project", root=str(tmp_path), config=config,
        http_post=_fake_extraction_http_post("unused"), qdrant_client=client,
    )
    assert len(results) == 1
    assert "SQLite" in results[0].text


def test_query_memory_excludes_pii_flagged_facts_when_allow_pii_false(tmp_path):
    config = _config(tmp_path)
    client = QdrantClient(":memory:")
    record_memory(
        "email me at jane@example.com about the deploy", scope="project", root=str(tmp_path),
        config=config, http_post=_fake_extraction_http_post("email me at jane@example.com about the deploy"),
        qdrant_client=client,
    )

    with_pii = query_memory("deploy", scope="project", root=str(tmp_path), allow_pii=True, config=config,
                             http_post=_fake_extraction_http_post("unused"), qdrant_client=client)
    without_pii = query_memory("deploy", scope="project", root=str(tmp_path), allow_pii=False, config=config,
                                http_post=_fake_extraction_http_post("unused"), qdrant_client=client)

    assert len(with_pii) == 1
    assert len(without_pii) == 0


def test_record_memory_degrades_gracefully_when_ollama_is_unreachable(tmp_path):
    config = _config(tmp_path)
    client = QdrantClient(":memory:")

    def failing_http_post(url, json_body, timeout=10.0):
        raise OSError("connection refused")

    facts = record_memory("raw session text with no model available", scope="project", root=str(tmp_path),
                           config=config, http_post=failing_http_post, qdrant_client=client)
    assert len(facts) == 1
    assert facts[0].category == "unclassified"  # extract_facts' own fallback, still saved


def test_query_memory_on_empty_store_returns_empty(tmp_path):
    config = _config(tmp_path)
    client = QdrantClient(":memory:")
    assert query_memory("anything", scope="project", root=str(tmp_path), config=config,
                         http_post=_fake_extraction_http_post("unused"), qdrant_client=client) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/memory/test_memory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.memory.memory'`

- [ ] **Step 3: Implement `memory.py`**

```python
# core/memory/memory.py
"""record_memory / query_memory — the two public verbs this sub-project
ships. Ties extraction, embedding, dual storage, and fused retrieval
together. Every failure mode inside a single fact's pipeline (embedding
fails, Qdrant unreachable) degrades that ONE fact to BM25-only rather
than aborting the whole call — same "handled state, not exception"
convention as core/index/query.py.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient

from core.audit.log import record_audit
from core.config.resolve import resolve_config_auto
from core.diagnostics.redact import contains_pii
from core.memory.embed import HttpPost, default_http_post, embed_text
from core.memory.extract import extract_facts
from core.memory.models import Fact
from core.memory.rank import reciprocal_rank_fusion
from core.memory.store import open_store, save_fact, search_fts
from core.memory.vectors import ensure_collection, search as vector_search, upsert_fact


def _qdrant_client(config: dict[str, Any]) -> QdrantClient:
    url = config.get("memory", {}).get("qdrant_url", "http://127.0.0.1:6333")
    return QdrantClient(url=url)


def record_memory(
    text: str,
    scope: str,
    root: str | None = None,
    session_id: str | None = None,
    config: dict[str, Any] | None = None,
    http_post: HttpPost = default_http_post,
    qdrant_client: QdrantClient | None = None,
) -> list[Fact]:
    config = config if config is not None else resolve_config_auto(root=Path(root) if root else None)
    conn = open_store(config, root=Path(root) if root else None)
    client = qdrant_client if qdrant_client is not None else _qdrant_client(config)
    dim = config.get("memory", {}).get("embedding_dim", 768)
    ensure_collection(client, dim=dim)

    try:
        pii = contains_pii(text)
        raw_facts = extract_facts(text, config, http_post=http_post)

        saved: list[Fact] = []
        for raw in raw_facts:
            fact = Fact(text=raw["text"], category=raw["category"], scope=scope, root=root, session_id=session_id, pii=pii, created_at=time.time())
            fact = save_fact(conn, fact)

            vector = embed_text(fact.text, config, http_post=http_post)
            if vector is not None:
                upsert_fact(client, fact_id=fact.id, vector=vector, scope=scope, root=root, pii=pii)
            saved.append(fact)

        record_audit(config, actor="record_memory", action=scope, target=root or session_id or "unscoped", result="success", detail={"fact_count": len(saved), "pii": pii})
        return saved
    finally:
        conn.close()


def query_memory(
    query: str,
    scope: str,
    root: str | None = None,
    allow_pii: bool = True,
    limit: int = 10,
    config: dict[str, Any] | None = None,
    http_post: HttpPost = default_http_post,
    qdrant_client: QdrantClient | None = None,
) -> list[Fact]:
    config = config if config is not None else resolve_config_auto(root=Path(root) if root else None)
    conn = open_store(config, root=Path(root) if root else None)
    client = qdrant_client if qdrant_client is not None else _qdrant_client(config)
    dim = config.get("memory", {}).get("embedding_dim", 768)
    ensure_collection(client, dim=dim)

    try:
        bm25_facts = search_fts(conn, query, scope=scope, root=root, limit=limit * 2)
        by_id = {f.id: f for f in bm25_facts}
        bm25_ids = [f.id for f in bm25_facts]

        vector_ids: list[int] = []
        query_vector = embed_text(query, config, http_post=http_post)
        if query_vector is not None:
            vector_ids = vector_search(client, query_vector, scope=scope, root=root, limit=limit * 2)

        fused_ids = reciprocal_rank_fusion(bm25_ids, vector_ids)

        # vector search can surface fact ids the BM25 pass didn't fetch —
        # look those up individually rather than dropping them.
        results: list[Fact] = []
        for fact_id in fused_ids:
            fact = by_id.get(fact_id)
            if fact is None:
                row = conn.execute("SELECT id, text, category, scope, root, session_id, pii, created_at FROM facts WHERE id = ?", (fact_id,)).fetchone()
                if row is None:
                    continue
                fact = Fact(id=row[0], text=row[1], category=row[2], scope=row[3], root=row[4], session_id=row[5], pii=bool(row[6]), created_at=row[7])
            results.append(fact)

        excluded_count = 0
        if not allow_pii:
            kept = [f for f in results if not f.pii]
            excluded_count = len(results) - len(kept)
            results = kept

        if excluded_count:
            record_audit(config, actor="query_memory", action=scope, target=root or "unscoped", result="success", detail={"pii_excluded_count": excluded_count})

        return results[:limit]
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests/memory/test_memory.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full memory test suite together**

Run: `python -m pytest core/tests/memory -v`
Expected: PASS (all tests across test_models.py, test_store.py, test_embed.py, test_extract.py, test_vectors.py, test_rank.py, test_memory.py)

- [ ] **Step 6: Run the full project test suite to confirm no regressions**

Run: `python -m pytest core/tests gateway/tests scripts/tests -q`
Expected: PASS, count increased by this plan's new tests (Tasks 1-8), no prior test broken. (Baseline before this plan: 226 passed, 4 skipped, per `docs/BACKLOG.md`'s code-index entry.)

- [ ] **Step 7: Commit**

```bash
git add core/memory/memory.py core/tests/memory/test_memory.py
git commit -m "feat(memory): record_memory/query_memory — the public verbs, hybrid retrieval + audit"
```

---

## Post-plan follow-ups (not part of this plan, log to `docs/BACKLOG.md` if not picked up immediately)

- MCP tool exposure for `record_memory`/`query_memory` (mirrors `verify_output`'s and the code index's eventual MCP wrapper).
- `kind="doc_chunk"` extension for general RAG (deliberately out of scope, per the design spec).
- Sub-project 3 (ingestion daemon) calling `record_memory` on a schedule/watch — the natural consumer of this sub-project's verbs.
- Session-scope TTL/cleanup — facts accumulate indefinitely today; not in the phase's acceptance criteria, worth a follow-up decision.
- `services.ollama`/`services.qdrant` real health checks in `core/diagnostics/checks.py` — currently `_not_yet_implemented` stubs; this plan's modules would benefit from `promptwise doctor` actually reporting whether they're reachable, following `_check_services_gateway`'s exact pattern.
- Dev-environment gap (pre-existing, not introduced here): this machine runs Python 3.11.5 while `pyproject.toml` declares `requires-python = ">=3.12"` — flagged in the code-index plan too, still unresolved.
