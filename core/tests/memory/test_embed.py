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
