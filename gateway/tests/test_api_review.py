"""Regressions from the adversarial review of the dashboard read API."""
import os
import stat
import sys

import pytest
from fastapi.testclient import TestClient

from core.audit.log import record_audit
from gateway import auth
from gateway.app import app
from gateway.mcp_guard import operator_config

TOKEN = "review-credential-0123456789abcdef0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cred").write_text(TOKEN, encoding="utf-8")
    monkeypatch.setenv("PROMPTWISE_GATEWAY__TOKEN_PATH", str(tmp_path / "cred"))
    monkeypatch.setenv("PROMPTWISE_AUDIT__LOG_PATH", str(tmp_path / "audit.jsonl"))
    auth.reset_denial_throttle()
    return TestClient(app), tmp_path


def test_unusable_credential_location_fails_closed_not_500(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "isdir").mkdir()
    monkeypatch.setenv("PROMPTWISE_GATEWAY__TOKEN_PATH", str(tmp_path / "isdir"))
    auth.reset_denial_throttle()
    response = TestClient(app).get("/api/v1/policy")
    assert response.status_code == 503
    assert response.json() == {"detail": "credential unavailable"}


def test_a_too_short_credential_file_is_refused_not_accepted(api):
    client, tmp = api
    (tmp / "cred").write_text("x", encoding="utf-8")
    assert client.get("/api/v1/policy", headers={"Authorization": "Bearer x"}).status_code == 503


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_new_credential_file_is_created_private(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROMPTWISE_GATEWAY__TOKEN_PATH", str(tmp_path / "fresh"))
    auth.load_or_create_token(operator_config())
    assert stat.S_IMODE((tmp_path / "fresh").stat().st_mode) == 0o600


def test_default_credential_location_is_outside_the_gateway_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PROMPTWISE_GATEWAY__TOKEN_PATH", raising=False)
    path = auth.token_path(operator_config())
    assert tmp_path not in path.parents and path.is_absolute()


def test_a_symlinked_credential_file_is_refused(api, tmp_path):
    client, tmp = api
    real = tmp / "real"
    real.write_text(TOKEN, encoding="utf-8")
    link = tmp / "link"
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    os.environ["PROMPTWISE_GATEWAY__TOKEN_PATH"] = str(link)
    try:
        assert client.get("/api/v1/policy", headers=AUTH).status_code == 503
    finally:
        os.environ["PROMPTWISE_GATEWAY__TOKEN_PATH"] = str(tmp / "cred")


def test_bearer_scheme_is_case_insensitive(api):
    client, _ = api
    assert client.get("/api/v1/policy", headers={"Authorization": f"bearer {TOKEN}"}).status_code == 200


def test_a_broken_project_config_cannot_take_the_read_api_down(api):
    client, tmp = api
    (tmp / ".promptwise").mkdir()
    (tmp / ".promptwise" / "config.yaml").write_text("verify: [unclosed\n", encoding="utf-8")
    assert client.get("/api/v1/audit", headers=AUTH).status_code == 200


def test_denials_are_throttled_per_client_and_path_and_record_the_client(api):
    import json

    client, tmp = api
    client.get("/api/v1/policy", headers={"Authorization": "Bearer nope"})
    client.get("/api/v1/audit", headers={"Authorization": "Bearer nope"})  # different path: not suppressed by the first
    client.get("/api/v1/audit", headers={"Authorization": "Bearer nope"})  # same path again: suppressed
    records = [json.loads(line) for line in (tmp / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    denials = [r for r in records if r["action"] == "api_auth_denied"]
    assert sorted(r["target"] for r in denials) == ["/api/v1/audit", "/api/v1/policy"]
    assert all("client" in r["detail"] for r in denials)


def test_huge_last_event_id_is_ignored_not_a_500(api):
    client, _ = api
    record_audit(operator_config(), actor="t", action="a", target="x", result="allow")
    os.environ["PROMPTWISE_GATEWAY__SSE_MAX_SECONDS"] = "0.2"
    try:
        with client.stream("GET", "/api/v1/events", headers={**AUTH, "Last-Event-ID": "9" * 5000}) as response:
            assert response.status_code == 200
    finally:
        del os.environ["PROMPTWISE_GATEWAY__SSE_MAX_SECONDS"]


def test_concurrent_event_streams_are_capped(api, monkeypatch):
    import gateway.api.v1 as v1

    client, _ = api
    monkeypatch.setattr(v1, "MAX_STREAMS", 0)
    assert client.get("/api/v1/events", headers=AUTH).status_code == 429
