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
