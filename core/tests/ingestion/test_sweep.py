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
