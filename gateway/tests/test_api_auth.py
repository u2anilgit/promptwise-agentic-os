import json
import stat
import sys

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from gateway import auth


@pytest.fixture
def secured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROMPTWISE_GATEWAY__TOKEN_PATH", str(tmp_path / "token"))
    monkeypatch.setenv("PROMPTWISE_AUDIT__LOG_PATH", str(tmp_path / "audit.jsonl"))
    auth.reset_denial_throttle()
    app = FastAPI()

    @app.get("/guarded", dependencies=[Depends(auth.require_token)])
    def guarded():
        return {"ok": True}

    return TestClient(app), tmp_path


def _token(tmp_path):
    return (tmp_path / "token").read_text(encoding="utf-8").strip()


def _denials(tmp_path):
    path = tmp_path / "audit.jsonl"
    if not path.exists():
        return []
    return [r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if r["action"] == "api_auth_denied"]


def test_token_is_created_on_first_use_and_stable(secured):
    client, tmp = secured
    assert client.get("/guarded").status_code == 401  # first request creates the token
    first = _token(tmp)
    assert len(first) >= 32
    assert client.get("/guarded", headers={"Authorization": f"Bearer {first}"}).status_code == 200
    assert _token(tmp) == first


@pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer ", "Basic abc", "bearer", "Token xyz", "Bearer wrong"])
def test_missing_or_bad_credentials_are_401_not_500(secured, header):
    client, _ = secured
    headers = {} if header is None else {"Authorization": header}
    response = client.get("/guarded", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "unauthorized"}


def test_a_near_miss_token_is_rejected(secured):
    client, tmp = secured
    client.get("/guarded")
    token = _token(tmp)
    for bad in (f"Bearer {token}x", f"Bearer x{token}", f"Bearer {token[:-1]}"):
        assert client.get("/guarded", headers={"Authorization": bad}).status_code == 401


def test_denial_is_audited_but_rate_limited(secured):
    client, tmp = secured
    for _ in range(5):
        client.get("/guarded", headers={"Authorization": "Bearer nope"})
    records = _denials(tmp)
    assert len(records) == 1
    assert "nope" not in json.dumps(records[0])  # the attempted credential is never logged


def test_replacing_the_token_file_rotates_the_token(secured):
    client, tmp = secured
    client.get("/guarded")
    old = _token(tmp)
    fresh = "rotated-value-0123456789abcdef0123456789"
    (tmp / "token").write_text(fresh, encoding="utf-8")
    assert client.get("/guarded", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    assert client.get("/guarded", headers={"Authorization": f"Bearer {fresh}"}).status_code == 200


def test_an_empty_token_file_is_regenerated_never_accepted(secured):
    client, tmp = secured
    (tmp / "token").write_text("", encoding="utf-8")
    assert client.get("/guarded", headers={"Authorization": "Bearer "}).status_code == 401
    assert len(_token(tmp)) >= 32


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_token_file_is_owner_only_where_supported(secured):
    client, tmp = secured
    client.get("/guarded")
    mode = stat.S_IMODE((tmp / "token").stat().st_mode)
    assert mode & 0o077 == 0
