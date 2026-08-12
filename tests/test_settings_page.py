from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.database.models import AppSetting
from app.database.session import SessionLocal
from app.main import app


def test_settings_page_exposes_editable_operational_settings_not_env_dump():
    response = TestClient(app).get("/settings")

    assert response.status_code == 200
    assert 'data-category="metadata"' in response.text
    assert 'name="cover_art_archive_timeout_seconds"' in response.text
    assert 'data-category="navidrome"' in response.text
    assert 'name="navidrome_playlist_reimport_enabled"' in response.text
    assert 'name="library_watcher_debounce_seconds"' in response.text
    assert 'id="settings-section-picker"' in response.text
    assert "min-height: 56px" in response.text
    assert "MUSICBRAINZ_BASE_URL" not in response.text
    assert "DATABASE_URL" not in response.text
    assert "NAVIDROME_PASSWORD" not in response.text
    assert 'data-category="playlists"' not in response.text
    assert 'name="default_download_source"' not in response.text
    assert 'name="playlist_sync_enabled"' not in response.text
    assert 'name="m3u_export_folder"' not in response.text
    assert 'data-category="spotify"' not in response.text
    assert 'name="spotify_genre_enrichment_enabled"' not in response.text


def test_retired_v2_settings_are_tolerated_but_not_exposed_or_updated():
    db = SessionLocal()
    try:
        db.add(AppSetting(key="playlist_sync_enabled", value="true", type="boolean", category="playlists"))
        db.commit()

        client = TestClient(app)
        assert "playlist_sync_enabled" not in client.get("/api/settings/playlists").json()
        assert client.put("/api/settings/playlists", json={"playlist_sync_enabled": False}).status_code == 200

        db.expire_all()
        assert db.get(AppSetting, "playlist_sync_enabled").value == "true"
    finally:
        db.close()


def test_retired_spotify_genre_settings_are_ignored():
    db = SessionLocal()
    try:
        db.add(
            AppSetting(
                key="spotify_genre_enrichment_enabled",
                value="true",
                type="boolean",
                category="spotify",
            )
        )
        db.commit()

        client = TestClient(app)
        assert "spotify_genre_enrichment_enabled" not in client.get(
            "/api/settings/spotify"
        ).json()
        client.put(
            "/api/settings/spotify",
            json={"spotify_genre_enrichment_enabled": False},
        )

        db.expire_all()
        assert db.get(AppSetting, "spotify_genre_enrichment_enabled").value == "true"
    finally:
        db.close()


def test_provider_diagnostics_api_is_not_part_of_v3_surface():
    client = TestClient(app)

    assert client.get("/api/providers/capabilities").status_code == 404
    assert client.get("/api/providers/status").status_code == 404


def test_runtime_setting_update_is_applied_and_persisted(monkeypatch):
    runtime = get_settings()
    monkeypatch.setattr(runtime, "navidrome_playlist_reimport_debounce_seconds", 10)
    client = TestClient(app)
    client.get("/settings")

    response = client.put(
        "/api/settings/navidrome",
        json={"navidrome_playlist_reimport_debounce_seconds": 40},
    )

    assert response.status_code == 200
    assert runtime.navidrome_playlist_reimport_debounce_seconds == 40
    assert client.get("/api/settings/navidrome").json()[
        "navidrome_playlist_reimport_debounce_seconds"
    ] == 40


def test_runtime_setting_update_rejects_out_of_range_value():
    client = TestClient(app)
    client.get("/settings")

    response = client.put(
        "/api/settings/navidrome",
        json={"navidrome_playlist_reimport_poll_seconds": 0},
    )

    assert response.status_code == 422
    assert "must be at least 0.25" in response.json()["detail"]
