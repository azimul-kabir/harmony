import json

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_manifest_is_installable_and_uses_root_scope():
    response = client.get("/manifest.webmanifest")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    assert response.headers["cache-control"] == "no-cache"
    manifest = json.loads(response.text)
    assert manifest["name"] == "Harmony"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert {icon["sizes"] for icon in manifest["icons"]} == {"192x192", "512x512"}


def test_service_worker_has_root_scope_and_does_not_cache_api_requests():
    response = client.get("/service-worker.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert response.headers["cache-control"] == "no-cache"
    assert 'CACHE_VERSION = "harmony-shell-v2"' in response.text
    assert 'url.pathname.startsWith("/api/")' in response.text
    assert 'request.mode === "navigate"' in response.text


def test_pwa_assets_are_served():
    for path, content_type in (
        ("/static/pwa/offline.html", "text/html"),
        ("/static/pwa/icon-192.png", "image/png"),
        ("/static/pwa/icon-512.png", "image/png"),
        ("/static/pwa/apple-touch-icon.png", "image/png"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(content_type)
