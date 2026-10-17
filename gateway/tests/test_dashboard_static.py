import pytest
from fastapi.testclient import TestClient

from gateway.app import create_app


@pytest.fixture
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html><body>dash</body></html>", encoding="utf-8")
    (root / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    return root


def _client(dist_dir):
    return TestClient(create_app(dashboard_dir=dist_dir))


def test_root_serves_the_index_with_security_headers(dist):
    response = _client(dist).get("/")
    assert response.status_code == 200 and "dash" in response.text
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert "unsafe-eval" not in csp and "unsafe-inline" not in csp.split("script-src")[-1].split(";")[0]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


def test_assets_are_served(dist):
    response = _client(dist).get("/assets/app.js")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"


def test_api_and_health_routes_win_over_the_static_mount(dist):
    client = _client(dist)
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/v1/policy").status_code == 401
    assert "content-security-policy" not in client.get("/healthz").headers


@pytest.mark.parametrize("path", ["/../secret.txt", "/..%2fsecret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt"])
def test_path_traversal_cannot_escape_the_bundle(dist, path):
    response = _client(dist).get(path)
    assert "outside" not in response.text


def test_without_a_built_bundle_the_app_still_starts_and_root_is_404(tmp_path):
    client = _client(tmp_path / "missing")
    assert client.get("/").status_code == 404
    assert client.get("/healthz").status_code == 200
