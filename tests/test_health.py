from fastapi.testclient import TestClient

from app.api import health
from app.core.config import get_settings
from app.main import app


client = TestClient(app)


def test_liveness_is_lightweight_and_versioned():
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": get_settings().app_version,
    }
    assert client.get("/health").json() == response.json()


def test_host_monitoring_is_outside_harmony_api():
    response = client.get("/api/system-health/synology")

    assert response.status_code == 404


def test_readiness_reports_database_and_storage_components(tmp_path, monkeypatch):
    settings = health.get_settings()
    for attribute in (
        "music_path",
        "download_path",
        "staging_path",
        "failed_path",
        "artwork_cache_path",
    ):
        directory = tmp_path / attribute
        directory.mkdir()
        monkeypatch.setattr(settings, attribute, str(directory))
    monkeypatch.setattr(
        health,
        "_database_check",
        lambda: {"status": "ok", "revision": "20260725_0026"},
    )

    response = client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["checks"]["database"]["revision"] == "20260725_0026"
    assert set(payload["checks"]) == {
        "database",
        "music",
        "downloads",
        "staging",
        "failed",
        "artwork_cache",
    }


def test_readiness_returns_503_with_safe_failure_reason(tmp_path, monkeypatch):
    settings = health.get_settings()
    missing = tmp_path / "missing"
    for attribute in (
        "music_path",
        "download_path",
        "staging_path",
        "failed_path",
        "artwork_cache_path",
    ):
        monkeypatch.setattr(settings, attribute, str(missing))

    def unavailable_database():
        raise RuntimeError("secret database detail")

    monkeypatch.setattr(health, "_database_check", unavailable_database)
    response = client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["checks"]["database"] == {
        "status": "error",
        "reason": "unavailable",
    }
    assert payload["checks"]["music"]["reason"] == "directory_missing"
