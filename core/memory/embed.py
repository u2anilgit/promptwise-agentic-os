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
