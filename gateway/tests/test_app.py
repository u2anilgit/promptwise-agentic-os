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
