from fastapi.testclient import TestClient

from gateway.app import app

client = TestClient(app)


def test_lifespan_writes_hardware_profile_on_boot(tmp_path, monkeypatch):
    profile_path = tmp_path / "hardware_profile.yaml"
    monkeypatch.setenv("PROMPTWISE_DIAGNOSTICS__HARDWARE_PROFILE_PATH", str(profile_path))
    with TestClient(app):
        pass
    assert profile_path.exists()


def test_healthz_returns_ok():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_diagnostics_returns_check_list():
    response = client.get("/diagnostics")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    names = {item["name"] for item in body}
    assert "config.resolve" in names


def test_diagnostics_status_field_is_valid():
    response = client.get("/diagnostics")
    for item in response.json():
        assert item["status"] in ("PASS", "WARN", "FAIL")


def test_route_endpoint_returns_a_decision():
    response = client.post("/route", json={"privacy_sensitive": True})
    assert response.status_code == 200
    body = response.json()
    assert body["tier"] in ("local-small", "local-large")
    assert "reason" in body


def test_route_endpoint_uses_default_request_body():
    response = client.post("/route", json={})
    assert response.status_code == 200
    assert response.json()["tier"] in ("local-small", "local-large", "cloud-cheap", "cloud-premium")


def test_cost_report_endpoint_computes_totals():
    response = client.post(
        "/cost-report",
        json=[
            {"tier": "local-small", "tokens_in": 1000, "tokens_out": 500},
            {"tier": "local-small", "tokens_in": 500, "tokens_out": 250},
        ],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["completed_tasks"] == 2
    assert body["total_cost_usd"] == 0.0


def test_cost_report_endpoint_with_no_records():
    response = client.post("/cost-report", json=[])
    assert response.status_code == 200
    assert response.json()["completed_tasks"] == 0
