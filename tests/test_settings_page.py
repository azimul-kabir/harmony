from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app


def test_settings_page_exposes_editable_operational_settings_not_env_dump():
    response = TestClient(app).get("/settings")

    assert response.status_code == 200
    assert 'data-category="metadata"' in response.text
    assert 'name="musicbrainz_timeout_seconds"' in response.text
    assert 'data-category="navidrome"' in response.text
    assert 'name="navidrome_direct_playlist_sync_enabled"' in response.text
    assert 'name="library_watcher_debounce_seconds"' in response.text
    assert "MUSICBRAINZ_BASE_URL" not in response.text
    assert "DATABASE_URL" not in response.text
    assert "NAVIDROME_PASSWORD" not in response.text


def test_runtime_setting_update_is_applied_and_persisted(monkeypatch):
    runtime = get_settings()
    monkeypatch.setattr(runtime, "navidrome_direct_search_limit", 25)
    client = TestClient(app)
    client.get("/settings")

    response = client.put(
        "/api/settings/navidrome",
        json={"navidrome_direct_search_limit": 40},
    )

    assert response.status_code == 200
    assert runtime.navidrome_direct_search_limit == 40
    assert client.get("/api/settings/navidrome").json()[
        "navidrome_direct_search_limit"
    ] == 40


def test_runtime_setting_update_rejects_out_of_range_value():
    client = TestClient(app)
    client.get("/settings")

    response = client.put(
        "/api/settings/navidrome",
        json={"navidrome_direct_search_limit": 0},
    )

    assert response.status_code == 422
    assert "must be at least 1" in response.json()["detail"]
