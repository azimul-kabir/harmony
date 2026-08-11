from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.web.playlists import _playlist_sync_status


def _playlist(*, tracks=10, synced=False):
    return SimpleNamespace(
        track_count=tracks,
        last_synced_at=datetime(2026, 7, 29) if synced else None,
    )


def test_playlist_sync_status_is_independent_of_playlist_type():
    assert _playlist_sync_status(_playlist(), 10) == "ready"
    assert _playlist_sync_status(_playlist(), 4) == "partial"
    assert _playlist_sync_status(_playlist(), 0) == "pending"
    assert _playlist_sync_status(_playlist(synced=True), 0) == "failed"


def test_playlist_page_orders_library_before_loved_section():
    template = Path("app/templates/playlists.html").read_text()

    assert template.index('class="sources-grid"') < template.index(
        'class="panel navidrome-love-panel"'
    )
    assert "auto-playlists-panel" not in template
    assert 'id="playlist-library-title">Your playlists</h2>' in template
    assert 'for="playlist-search"' in template


def test_auto_playlist_api_is_not_part_of_v3_surface():
    client = TestClient(app)

    assert client.get("/api/playlists/auto/definitions").status_code == 404
    assert client.post("/api/playlists/auto/recently-added/generate", json={}).status_code == 404


def test_playlist_navidrome_scan_has_endpoint_wiring_and_live_feedback():
    template = Path("app/templates/playlists.html").read_text()
    script = Path("app/static/js/playlists.js").read_text()

    assert 'id="scan-navidrome"' in template
    assert 'id="scan-navidrome-status"' in template
    assert 'fetch("/api/navidrome/rescan?full_scan=false"' in script
    assert 'fetch("/api/navidrome/status")' in script
    assert "payload.accepted !== true" in script
    assert "Navidrome scan completed." in script
