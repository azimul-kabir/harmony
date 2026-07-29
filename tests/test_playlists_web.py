from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

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


def test_playlist_page_orders_library_before_loved_and_auto_sections():
    template = Path("app/templates/playlists.html").read_text()

    assert template.index('class="sources-grid"') < template.index(
        'class="panel navidrome-love-panel"'
    ) < template.index('class="panel auto-playlists-panel"')
    assert 'id="playlist-library-title">Your playlists</h2>' in template
    assert 'for="playlist-search"' in template
