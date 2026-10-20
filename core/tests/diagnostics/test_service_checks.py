"""services.ollama / services.qdrant probe the configured endpoints (offline is a WARN, never a FAIL), and
governance.exposure warns when operator-owned governance files sit where an agent can write them."""
import io
import json

import pytest

from core.diagnostics import checks


class _Response(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serve(monkeypatch, routes):
    seen = []

    def urlopen(url, timeout=None):
        seen.append(url)
        for prefix, body in routes.items():
            if url.startswith(prefix):
                if isinstance(body, Exception):
                    raise body
                return _Response(body)
        raise OSError("connection refused")

    monkeypatch.setattr(checks.urllib.request, "urlopen", urlopen)
    return seen


CONFIG = {"memory": {"ollama_base_url": "http://ollama.test:11434", "qdrant_url": "http://qdrant.test:6333", "embedding_model": "nomic-embed-text"}}


def test_ollama_pass_lists_models_and_flags_a_missing_embedding_model(monkeypatch):
    _serve(monkeypatch, {"http://ollama.test:11434/api/tags": json.dumps({"models": [{"name": "llama3.2:3b"}]}).encode()})
    result = checks._check_services_ollama(CONFIG)
    assert result.status == "WARN"
    assert "nomic-embed-text" in result.message and "ollama pull" in result.message


def test_ollama_pass_when_the_embedding_model_is_present(monkeypatch):
    body = json.dumps({"models": [{"name": "nomic-embed-text:latest"}, {"name": "llama3.2:3b"}]}).encode()
    _serve(monkeypatch, {"http://ollama.test:11434/api/tags": body})
    result = checks._check_services_ollama(CONFIG)
    assert result.status == "PASS" and "2 model(s)" in result.message


def test_unreachable_services_warn_and_never_raise(monkeypatch):
    _serve(monkeypatch, {})
    assert checks._check_services_ollama(CONFIG).status == "WARN"
    assert checks._check_services_qdrant(CONFIG).status == "WARN"


def test_garbage_from_ollama_is_a_warn(monkeypatch):
    _serve(monkeypatch, {"http://ollama.test:11434/api/tags": b"<html>not json</html>"})
    assert checks._check_services_ollama(CONFIG).status == "WARN"


def test_qdrant_pass_when_ready(monkeypatch):
    seen = _serve(monkeypatch, {"http://qdrant.test:6333/readyz": b"all shards are ready"})
    assert checks._check_services_qdrant(CONFIG).status == "PASS"
    assert seen == ["http://qdrant.test:6333/readyz"]


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x/", "not a url"])
def test_only_http_endpoints_are_probed(monkeypatch, url):
    seen = _serve(monkeypatch, {})
    result = checks._check_services_qdrant({"memory": {"qdrant_url": url}})
    assert result.status == "WARN" and seen == []


def test_governance_exposure_warns_for_files_inside_the_allowed_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = checks._check_governance_exposure({})
    assert result.status == "WARN"
    for name in ("audit log", "policies", "tool registry"):
        assert name in result.message


def test_governance_exposure_passes_when_relocated(tmp_path, monkeypatch):
    project = tmp_path / "project"
    operator = tmp_path / "operator"
    project.mkdir()
    monkeypatch.chdir(project)
    config = {
        "gateway": {"allowed_roots": [str(project)]},
        "audit": {"log_path": str(operator / "audit.jsonl")},
        "paths": {"policies_dir": str(operator / "policies"), "model_catalog": str(operator / "catalog.yaml")},
        "policy": {"tool_registry_path": str(operator / "tool_registry.yaml"), "jit_grants_path": str(operator / "grants.json")},
        "database": {"path": str(operator / "agentic.sqlite3")},
    }
    config["gateway"]["token_path"] = str(operator / "token")
    result = checks._check_governance_exposure(config)
    assert result.status == "PASS", result.message
