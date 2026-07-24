from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.database.models import Playlist
from app.database.session import SessionLocal
from app.main import app
from app.services.playlist_manager import playlist_artwork_path, playlist_file_path


PNG = b"\x89PNG\r\n\x1a\n" + b"playlist-cover"
JPEG = b"\xff\xd8\xff\xe0" + b"playlist-cover"


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _playlist(db, name="Night Drive"):
    playlist = Playlist(spotify_id=f"playlist-{name}", name=name)
    db.add(playlist)
    db.commit()
    db.refresh(playlist)
    return playlist


def test_playlist_artwork_upload_replaces_sidecar_and_serves_it(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "music_path", str(tmp_path))
    playlist = _playlist(db_session)
    old_path = playlist_file_path(playlist.name).with_suffix(".jpg")
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(JPEG)

    client = TestClient(app)
    response = client.post(
        f"/api/playlists/{playlist.id}/artwork",
        files={"artwork": ("cover.png", PNG, "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["filename"] == "Night Drive.png"
    assert not old_path.exists()
    assert playlist_artwork_path(playlist.name).read_bytes() == PNG

    served = client.get(f"/api/playlists/{playlist.id}/artwork")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content == PNG


def test_playlist_artwork_rejects_invalid_or_oversized_images(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "music_path", str(tmp_path))
    playlist = _playlist(db_session)
    client = TestClient(app)

    invalid = client.post(
        f"/api/playlists/{playlist.id}/artwork",
        files={"artwork": ("cover.png", b"not-an-image", "image/png")},
    )
    assert invalid.status_code == 415

    oversized = client.post(
        f"/api/playlists/{playlist.id}/artwork",
        files={
            "artwork": (
                "cover.jpg",
                b"\xff\xd8\xff" + (b"x" * (10 * 1024 * 1024)),
                "image/jpeg",
            )
        },
    )
    assert oversized.status_code == 413
    assert playlist_artwork_path(playlist.name) is None


def test_playlist_artwork_delete_removes_all_sidecars(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "music_path", str(tmp_path))
    playlist = _playlist(db_session)
    base = playlist_file_path(playlist.name).with_suffix("")
    base.parent.mkdir(parents=True)
    base.with_suffix(".jpg").write_bytes(JPEG)
    base.with_suffix(".png").write_bytes(PNG)

    response = TestClient(app).delete(f"/api/playlists/{playlist.id}/artwork")

    assert response.status_code == 200
    assert playlist_artwork_path(playlist.name) is None


def test_playlists_page_shows_cover_controls(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "music_path", str(tmp_path))
    playlist = _playlist(db_session)
    artwork = playlist_file_path(playlist.name).with_suffix(".png")
    artwork.parent.mkdir(parents=True)
    artwork.write_bytes(PNG)

    response = TestClient(app).get("/playlists")

    assert response.status_code == 200
    assert f'src="/api/playlists/{playlist.id}/artwork"' in response.text
    assert 'class="btn-secondary playlist-artwork-btn"' in response.text
    assert 'id="playlist-artwork-dialog"' in response.text
