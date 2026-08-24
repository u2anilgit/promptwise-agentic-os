# Ingestion Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `run_ingestion_sweep` — one idempotent verb that refreshes the code index and records caller-supplied session text as memory facts, so an external scheduler (cron/systemd/Task Scheduler) can keep both sub-projects fresh without a persistent daemon process.

**Architecture:** `core/ingestion/` — one model file, one function file. Pure composition over two already-merged, already-reviewed verbs (`query_code_index`, `record_memory`); no new datastore, no new HTTP surface, no new dependency.

**Tech Stack:** Python 3.12 (repo's declared floor), Pydantic v2. No new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-08-24-ingestion-daemon-design.md`

## Global Constraints

- Never crash on malformed input: a code-index-refresh failure or a per-text `record_memory` failure are both handled states (accumulate in `errors`, keep going), never exceptions that abort the whole sweep.
- No verb reads a config file directly — `config` threads through to both consumed verbs as received, or resolves once via `resolve_config_auto(root=root)` if not supplied.
- Pydantic v2 `BaseModel` for the typed contract (`IngestionResult`).
- TDD: failing test before implementation.
- Dependency injection for network calls — `http_post`/`qdrant_client` pass straight through to `record_memory`, not reinvented here.
- This sub-project does NOT start a background process, register a filesystem watcher, or read any file/transcript on its own — `session_texts` is caller-supplied only (spec Ruling 2).

## Verified interfaces this plan depends on (hand-checked against the real source on master, not assumed)

```python
# core/index/query.py — already merged, already reviewed
def query_code_index(
    symbol: str,
    kind: str | None = None,
    root: Path | None = None,
    config: dict[str, Any] | None = None,
) -> list[CodeLocation]:
    root = root if root is not None else Path.cwd()
    if not root.is_dir():
        return []
    # ... walks + incrementally reindexes root as a side effect, then answers the query.
# query_symbol's SQL is "WHERE symbol LIKE ?" with params=[f"%{symbol}%"] — an empty symbol
# ("") produces LIKE '%%', which matches every row. The reindex side effect (the walk, which
# runs unconditionally before the query answers) is the only reason this plan calls it; the
# returned list is discarded.

# core/memory/memory.py — already merged, already reviewed
def record_memory(
    text: str,
    scope: str,
    root: str | None = None,
    session_id: str | None = None,
    config: dict[str, Any] | None = None,
    http_post: HttpPost = default_http_post,
    qdrant_client: QdrantClient | None = None,
) -> list[Fact]:
    """Extract facts from `text` and persist them (SQLite + best-effort
    Qdrant vector). NOTE: session_id is accepted and persisted, but
    query_memory does not currently filter by it (docs/BACKLOG.md).
    """
    ...

# core/memory/embed.py
from core.memory.embed import HttpPost, default_http_post  # re-export for this plan's signature

# core/config/resolve.py
def resolve_config_auto(root: Path | None = None, env: Mapping[str, str] | None = None) -> dict[str, Any]: ...
```

---

### Task 1: `core/ingestion/models.py` — `IngestionResult`

**Files:**
- Create: `core/ingestion/__init__.py` (empty)
- Create: `core/ingestion/models.py`
- Test: `core/tests/ingestion/__init__.py` (empty), `core/tests/ingestion/test_models.py`

**Interfaces:**
- Produces: `IngestionResult` (Pydantic v2 model) — consumed by Task 2.

- [ ] **Step 1: Write the failing test**

`core/tests/ingestion/test_models.py`:
```python
from core.ingestion.models import IngestionResult


def test_ingestion_result_defaults():
    result = IngestionResult(root="/repo")
    assert result.root == "/repo"
    assert result.code_index_refreshed is False
    assert result.facts_recorded == 0
    assert result.facts_failed == 0
    assert result.errors == []


def test_ingestion_result_all_fields():
    result = IngestionResult(
        root="/repo", code_index_refreshed=True, facts_recorded=3, facts_failed=1,
        errors=["record_memory failed for session_texts[2]: connection refused"],
    )
    assert result.code_index_refreshed is True
    assert result.facts_recorded == 3
    assert result.facts_failed == 1
    assert len(result.errors) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/ingestion/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.ingestion'`

- [ ] **Step 3: Implement `models.py`**

```python
# core/ingestion/models.py
from pydantic import BaseModel


class IngestionResult(BaseModel):
    root: str
    code_index_refreshed: bool = False
    facts_recorded: int = 0
    facts_failed: int = 0
    errors: list[str] = []
```

- [ ] **Step 4: Add `core/ingestion/__init__.py` and `core/tests/ingestion/__init__.py`** (both empty, same convention as `core/memory/__init__.py`/`core/tests/memory/__init__.py`)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest core/tests/ingestion/test_models.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add core/ingestion/__init__.py core/ingestion/models.py core/tests/ingestion/__init__.py core/tests/ingestion/test_models.py
git commit -m "feat(ingestion): IngestionResult model"
```

---

### Task 2: `core/ingestion/sweep.py` — `run_ingestion_sweep`

**Files:**
- Create: `core/ingestion/sweep.py`
- Test: `core/tests/ingestion/test_sweep.py`

**Interfaces:**
- Consumes: `IngestionResult` (Task 1), `query_code_index` (`core/index/query.py`, verified signature above), `record_memory`/`HttpPost`/`default_http_post` (`core/memory/memory.py`/`core/memory/embed.py`, verified signatures above), `resolve_config_auto` (`core/config/resolve.py`).
- Produces: `run_ingestion_sweep(root: Path, session_texts: list[str] | None = None, session_id: str | None = None, config: dict[str, Any] | None = None, http_post: HttpPost = default_http_post, qdrant_client: QdrantClient | None = None) -> IngestionResult` — the sub-project's one public verb.

- [ ] **Step 1: Write the failing tests**

`core/tests/ingestion/test_sweep.py`:
```python
from pathlib import Path

from qdrant_client import QdrantClient

from core.ingestion.sweep import run_ingestion_sweep


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _config(tmp_path):
    return {
        "engine": {"local_only": True},
        "routing": {"default_tier": "local-small"},
        "index": {"db_path": str(tmp_path / "code_index.sqlite3")},
        "memory": {
            "db_path": str(tmp_path / "memory.sqlite3"),
            "embedding_model": "nomic-embed-text",
            "embedding_dim": 4,
            "extraction_tier_hint": "local-small",
        },
        "audit": {"log_path": str(tmp_path / "audit.jsonl")},
    }


def _fake_http_post(fact_text="a fact"):
    def _post(url, json_body, timeout=10.0):
        if url.endswith("/api/generate"):
            return {"response": f'{{"facts": [{{"text": "{fact_text}", "category": "context"}}]}}'}
        if url.endswith("/api/embeddings"):
            return {"embedding": [0.1, 0.2, 0.3, 0.4]}
        raise AssertionError(f"unexpected url {url}")
    return _post


def test_run_ingestion_sweep_refreshes_the_code_index(tmp_path):
    _write(tmp_path / "a.py", "def alpha():\n    pass\n")
    config = _config(tmp_path)

    result = run_ingestion_sweep(tmp_path, config=config)

    assert result.code_index_refreshed is True
    assert result.root == str(tmp_path)


def test_run_ingestion_sweep_records_session_texts_as_facts(tmp_path):
    config = _config(tmp_path)
    client = QdrantClient(":memory:")

    result = run_ingestion_sweep(
        tmp_path, session_texts=["decided: ship the sweep verb, not a daemon"], session_id="s1",
        config=config, http_post=_fake_http_post("decided: ship the sweep verb, not a daemon"),
        qdrant_client=client,
    )

    assert result.facts_recorded == 1
    assert result.facts_failed == 0
    assert result.errors == []


def test_run_ingestion_sweep_with_no_session_texts_records_nothing(tmp_path):
    config = _config(tmp_path)
    result = run_ingestion_sweep(tmp_path, config=config)
    assert result.facts_recorded == 0
    assert result.facts_failed == 0


def test_run_ingestion_sweep_survives_a_code_index_refresh_failure(tmp_path, monkeypatch):
    config = _config(tmp_path)

    def raising_query_code_index(symbol, kind=None, root=None, config=None):
        raise OSError("disk full")

    monkeypatch.setattr("core.ingestion.sweep.query_code_index", raising_query_code_index)

    result = run_ingestion_sweep(tmp_path, config=config)
    assert result.code_index_refreshed is False
    assert len(result.errors) == 1
    assert "code index" in result.errors[0].lower()


def test_run_ingestion_sweep_still_records_facts_when_ollama_is_down_via_fallback(tmp_path):
    # extract_facts' own fallback (already reviewed/merged in the memory sub-project) still
    # produces one unclassified fact per text on a failed extraction call — record_memory
    # itself does not raise here, so this is NOT the sweep-level failure-handling path. That
    # path (record_memory raising outright) is exercised by the next test below.
    config = _config(tmp_path)
    client = QdrantClient(":memory:")

    def failing_http_post(url, json_body, timeout=10.0):
        raise OSError("connection refused")

    result = run_ingestion_sweep(
        tmp_path, session_texts=["first text", "second text"], session_id="s1",
        config=config, http_post=failing_http_post, qdrant_client=client,
    )

    assert result.facts_recorded == 2  # unclassified-fact fallback, not a sweep-level failure
    assert result.facts_failed == 0
    assert result.errors == []


def test_run_ingestion_sweep_survives_record_memory_raising_outright(tmp_path, monkeypatch):
    config = _config(tmp_path)
    client = QdrantClient(":memory:")

    def raising_record_memory(*args, **kwargs):
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr("core.ingestion.sweep.record_memory", raising_record_memory)

    result = run_ingestion_sweep(
        tmp_path, session_texts=["first text", "second text"], session_id="s1",
        config=config, http_post=_fake_http_post(), qdrant_client=client,
    )

    assert result.facts_recorded == 0
    assert result.facts_failed == 2
    assert len(result.errors) == 2
    assert "session_texts[0]" in result.errors[0]
    assert "session_texts[1]" in result.errors[1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest core/tests/ingestion/test_sweep.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.ingestion.sweep'`

- [ ] **Step 3: Implement `sweep.py`**

```python
# core/ingestion/sweep.py
"""run_ingestion_sweep — the one verb this sub-project ships. Refreshes
the code index (a side effect of query_code_index's own walk) and
records caller-supplied session text as memory facts. NOT a background
process: this function runs once per call and returns; scheduling it
is an ops concern (cron/systemd/Task Scheduler), not this module's job
(design spec Ruling 1). Every step is independently fail-soft — a
code-index failure doesn't block fact recording and vice versa, and one
failed text block doesn't block its siblings (design spec's Global
Constraints).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient

from core.config.resolve import resolve_config_auto
from core.index.query import query_code_index
from core.ingestion.models import IngestionResult
from core.memory.embed import HttpPost, default_http_post
from core.memory.memory import record_memory


def run_ingestion_sweep(
    root: Path,
    session_texts: list[str] | None = None,
    session_id: str | None = None,
    config: dict[str, Any] | None = None,
    http_post: HttpPost = default_http_post,
    qdrant_client: QdrantClient | None = None,
) -> IngestionResult:
    config = config if config is not None else resolve_config_auto(root=root)
    result = IngestionResult(root=str(root))

    try:
        query_code_index("", root=root, config=config)  # side effect only, result discarded
        result.code_index_refreshed = True
    except Exception as exc:  # noqa: BLE001 — one failed subsystem must not abort the sweep
        result.errors.append(f"code index refresh failed: {exc}")

    for index, text in enumerate(session_texts or []):
        try:
            facts = record_memory(
                text, scope="session", root=str(root), session_id=session_id,
                config=config, http_post=http_post, qdrant_client=qdrant_client,
            )
            result.facts_recorded += len(facts)
        except Exception as exc:  # noqa: BLE001 — one failed text block must not abort the rest
            result.facts_failed += 1
            result.errors.append(f"record_memory failed for session_texts[{index}]: {exc}")

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest core/tests/ingestion/test_sweep.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run the full ingestion test suite together**

Run: `python -m pytest core/tests/ingestion -v`
Expected: PASS (all tests across test_models.py, test_sweep.py)

- [ ] **Step 6: Run the full project test suite to confirm no regressions**

Run: `python -m pytest core/tests gateway/tests scripts/tests -q`
Expected: PASS, count increased by this plan's new tests (Tasks 1-2), no prior test broken. (Baseline before this plan: 266 passed, 4 skipped, per `docs/BACKLOG.md`'s memory-fact-layer entry.)

- [ ] **Step 7: Commit**

```bash
git add core/ingestion/sweep.py core/tests/ingestion/test_sweep.py
git commit -m "feat(ingestion): run_ingestion_sweep — refresh code index + record session facts"
```

---

## Post-plan follow-ups (not part of this plan, log to `docs/BACKLOG.md` if not picked up immediately)

- A reference ops recipe (cron entry / systemd timer / Task Scheduler task) that calls `run_ingestion_sweep` on a cadence — this plan ships the verb, not the invocation job.
- Automatic session-transcript capture / watched-folder ingestion, once a policy model exists for "what may be auto-ingested" (design spec Ruling 2's deferred real daemon behavior).
- MCP tool exposure for `run_ingestion_sweep`, mirroring the other two sub-projects' eventual MCP wrappers.
