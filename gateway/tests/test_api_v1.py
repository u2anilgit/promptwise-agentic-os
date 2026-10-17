import asyncio
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.audit.log import record_audit
from core.spec.engine import plan_feature, specify_feature
from gateway import auth
from gateway.app import app
from gateway.mcp_guard import effective_config, operator_config

TOKEN = "test-api-credential-0123456789abcdef0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "token").write_text(TOKEN, encoding="utf-8")
    monkeypatch.setenv("PROMPTWISE_GATEWAY__TOKEN_PATH", str(tmp_path / "token"))
    monkeypatch.setenv("PROMPTWISE_AUDIT__LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("PROMPTWISE_GATEWAY__SSE_MAX_SECONDS", "0.6")
    monkeypatch.setenv("PROMPTWISE_GATEWAY__SSE_POLL_SECONDS", "0.1")
    (tmp_path / "policies").mkdir()
    (tmp_path / "policies" / "rules.yaml").write_text(
        "rules:\n  - action: 'shell:run:python'\n    effect: allow\n  - action: 'fs:write:*'\n    effect: deny\n", encoding="utf-8"
    )
    auth.reset_denial_throttle()
    return TestClient(app), tmp_path


def _cfg():
    return effective_config(operator_config(), Path.cwd())


def _audit(n=3, action="a", result="allow"):
    cfg = _cfg()
    return [record_audit(cfg, actor="t", action=action, target=f"x{i}", result=result) for i in range(n)]


API_GETS = ["/api/v1/audit", "/api/v1/specs", "/api/v1/specs/abc", "/api/v1/policy", "/api/v1/diagnostics", "/api/v1/events"]
LEGACY = [("get", "/diagnostics"), ("post", "/route"), ("post", "/cost-report"), ("post", "/verify")]


@pytest.mark.parametrize("path", API_GETS)
def test_every_api_route_requires_auth(api, path):
    client, _ = api
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401


@pytest.mark.parametrize("method,path", LEGACY)
def test_legacy_routes_now_require_auth(api, method, path):
    client, _ = api
    assert getattr(client, method)(path).status_code == 401


def test_healthz_stays_open(api):
    client, _ = api
    assert client.get("/healthz").status_code == 200


def test_the_api_surface_is_read_only(api):
    paths = {p: ops for p, ops in app.openapi()["paths"].items() if p.startswith("/api/v1")}
    assert len(paths) >= 6
    for path, operations in paths.items():
        assert set(operations) == {"get"}, path


def test_audit_pages_with_cursor_and_reports_chain_ok(api):
    client, _ = api
    written = _audit(5)
    first = client.get("/api/v1/audit?limit=2", headers=AUTH).json()
    assert [r["id"] for r in first["records"]] == [r.id for r in written[:2]]
    assert first["chain"] == {"ok": True, "broken_at": None}
    second = client.get(f"/api/v1/audit?limit=10&cursor={first['next_cursor']}", headers=AUTH).json()
    assert [r["id"] for r in second["records"]] == [r.id for r in written[2:]]


def test_audit_tail_filters_and_validation(api):
    client, _ = api
    _audit(3, action="a")
    _audit(2, action="b", result="deny")
    tail = client.get("/api/v1/audit?tail=true&limit=2&action=b", headers=AUTH).json()
    assert [r["action"] for r in tail["records"]] == ["b", "b"]
    assert client.get("/api/v1/audit?result=bogus", headers=AUTH).status_code == 422
    assert client.get("/api/v1/audit?limit=0", headers=AUTH).status_code == 422
    assert client.get("/api/v1/audit?limit=1000000000", headers=AUTH).status_code == 422
    assert client.get("/api/v1/audit?cursor=-1", headers=AUTH).status_code == 422


def test_tampered_audit_reports_a_broken_chain_not_an_error(api):
    client, tmp = api
    _audit(3)
    path = tmp / "audit.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["target"] = "tampered"
    lines[1] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    response = client.get("/api/v1/audit", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["chain"] == {"ok": False, "broken_at": 1}


def test_specs_list_and_detail(api):
    client, tmp = api
    assert client.get("/api/v1/specs", headers=AUTH).json() == []
    cfg = _cfg()
    spec = specify_feature("login", ["The system shall log in users."], config=cfg, root=tmp)
    plan_feature(spec.spec_id, "approach", config=cfg, root=tmp)
    listed = client.get("/api/v1/specs", headers=AUTH).json()
    assert [(s["spec_id"], s["stage"]) for s in listed] == [(spec.spec_id, "planned")]
    detail = client.get(f"/api/v1/specs/{spec.spec_id}", headers=AUTH).json()
    assert detail["request"] == "login" and detail["requirements"][0]["id"] == "R1"


@pytest.mark.parametrize("bad", ["nope", "..%2F..%2Fetc", "a'%20OR%201=1", "%00"])
def test_unknown_or_hostile_spec_id_is_a_plain_404(api, bad):
    client, _ = api
    response = client.get(f"/api/v1/specs/{bad}", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["detail"] in ("not found", "Not Found")
    assert "etc" not in response.text and "sqlite" not in response.text.lower()


def test_policy_view_shows_rules_and_default(api):
    client, _ = api
    body = client.get("/api/v1/policy", headers=AUTH).json()
    assert body["default_effect"] == "deny"
    assert {"action": "shell:run:python", "effect": "allow"} in body["rules"]


def test_diagnostics_view(api):
    client, _ = api
    body = client.get("/api/v1/diagnostics", headers=AUTH).json()
    assert "config.resolve" in {item["name"] for item in body}


def test_events_stream_replays_from_cursor_with_ids_and_ends_on_its_own(api):
    client, _ = api
    written = _audit(2)
    with client.stream("GET", "/api/v1/events?cursor=0", headers=AUTH) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        text = "".join(response.iter_text())
    events = [block for block in text.split("\n\n") if "event: audit" in block]
    assert len(events) == 2
    assert json.loads(events[0].split("data: ", 1)[1])["id"] == written[0].id
    last_id = int([line for line in events[-1].splitlines() if line.startswith("id: ")][0][4:])
    with client.stream("GET", "/api/v1/events", headers={**AUTH, "Last-Event-ID": str(last_id)}) as response:
        assert "event: audit" not in "".join(response.iter_text())


def test_events_default_starts_at_the_end_of_the_log(api):
    client, _ = api
    _audit(3)
    with client.stream("GET", "/api/v1/events", headers=AUTH) as response:
        assert "event: audit" not in "".join(response.iter_text())


def test_event_generator_delivers_records_appended_after_connect(api):
    from gateway.api.v1 import audit_events

    _, _ = api
    cfg = _cfg()

    async def collect():
        out = []
        async for chunk in audit_events(cfg, cursor=0, max_seconds=1.5, poll_seconds=0.05):
            out.append(chunk)
            if "event: audit" in chunk:
                break
        return out

    def late_writer():
        time.sleep(0.3)
        record_audit(cfg, actor="t", action="late", target="z", result="allow")

    thread = threading.Thread(target=late_writer)
    thread.start()
    chunks = asyncio.run(collect())
    thread.join()
    assert any('"action": "late"' in c or '"action":"late"' in c for c in chunks)
