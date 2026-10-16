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


def upsert_fact(client: QdrantClient, fact_id: int, vector: list[float], scope: str, root: str | None, pii: bool, session_id: str | None = None) -> None:
    client.upsert(
        COLLECTION_NAME,
        points=[PointStruct(id=fact_id, vector=vector, payload={"scope": scope, "root": root, "pii": pii, "session_id": session_id})],
    )


def search(client: QdrantClient, query_vector: list[float], scope: str, root: str | None = None, limit: int = 20, session_id: str | None = None) -> list[int]:
    must = [FieldCondition(key="scope", match=MatchValue(value=scope))]
    if root is not None:
        must.append(FieldCondition(key="root", match=MatchValue(value=root)))
    if session_id is not None:
        must.append(FieldCondition(key="session_id", match=MatchValue(value=session_id)))

    response = client.query_points(COLLECTION_NAME, query=query_vector, query_filter=Filter(must=must), limit=limit)
    return [point.id for point in response.points]
