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


class _UnreachableQdrantClient:
    """Simulates a Qdrant host that cannot even be reached — every method
    raises, including collection_exists (called from ensure_collection)."""

    def __getattr__(self, name):
        def _raise(*args, **kwargs):
            raise OSError("[WinError 10061] No connection could be made")
        return _raise


def test_record_memory_degrades_gracefully_when_qdrant_is_unreachable(tmp_path):
    config = _config(tmp_path)
    client = _UnreachableQdrantClient()

    facts = record_memory(
        "I always use pytest, never unittest", scope="project", root=str(tmp_path),
        config=config, http_post=_fake_extraction_http_post("user prefers pytest"), qdrant_client=client,
    )

    assert len(facts) == 1
    assert facts[0].text == "user prefers pytest"


def test_query_memory_degrades_gracefully_when_qdrant_is_unreachable(tmp_path):
    config = _config(tmp_path)
    healthy_client = QdrantClient(":memory:")
    record_memory(
        "decided: SQLite for dev, Postgres for prod", scope="project", root=str(tmp_path),
        config=config, http_post=_fake_extraction_http_post("decided: SQLite for dev, Postgres for prod", "decision"),
        qdrant_client=healthy_client,
    )

    unreachable_client = _UnreachableQdrantClient()
    results = query_memory(
        "SQLite", scope="project", root=str(tmp_path), config=config,
        http_post=_fake_extraction_http_post("unused"), qdrant_client=unreachable_client,
    )

    # Qdrant unreachable end-to-end — still resolves via BM25 alone.
    assert len(results) == 1
    assert "SQLite" in results[0].text


class _CollectionExistsOkThenDiesClient:
    """Simulates a Qdrant that answers ensure_collection's probe fine but
    then fails on the actual upsert/search call — the "mid-call" failure
    mode, distinct from total unreachability."""

    def __init__(self):
        self._delegate = QdrantClient(":memory:")

    def collection_exists(self, *args, **kwargs):
        return self._delegate.collection_exists(*args, **kwargs)

    def create_collection(self, *args, **kwargs):
        return self._delegate.create_collection(*args, **kwargs)

    def upsert(self, *args, **kwargs):
        raise OSError("qdrant went away")

    def query_points(self, *args, **kwargs):
        raise OSError("qdrant went away")


def test_record_memory_still_saves_fact_when_upsert_fails_mid_call(tmp_path):
    config = _config(tmp_path)
    client = _CollectionExistsOkThenDiesClient()

    facts = record_memory(
        "I always use pytest, never unittest", scope="project", root=str(tmp_path),
        config=config, http_post=_fake_extraction_http_post("user prefers pytest"), qdrant_client=client,
    )

    assert len(facts) == 1
    assert facts[0].text == "user prefers pytest"
    assert facts[0].id is not None


def test_query_memory_degrades_to_bm25_when_vector_search_fails_mid_call(tmp_path):
    config = _config(tmp_path)

    # Record with a healthy client so the fact is BM25-searchable.
    healthy_client = QdrantClient(":memory:")
    record_memory(
        "decided: SQLite for dev, Postgres for prod", scope="project", root=str(tmp_path),
        config=config, http_post=_fake_extraction_http_post("decided: SQLite for dev, Postgres for prod", "decision"),
        qdrant_client=healthy_client,
    )

    dying_client = _CollectionExistsOkThenDiesClient()
    results = query_memory(
        "SQLite", scope="project", root=str(tmp_path), config=config,
        http_post=_fake_extraction_http_post("unused"), qdrant_client=dying_client,
    )

    assert len(results) == 1
    assert "SQLite" in results[0].text
