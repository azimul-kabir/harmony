from fastapi.testclient import TestClient

from app.api.playlist import playlist_tracks
from app.database.models import Playlist, PlaylistTrack, Song
from app.database.session import SessionLocal
from app.main import app


def test_playlist_tracks_preserve_order_and_mark_delete_candidates():
    db = SessionLocal()
    try:
        playlist = Playlist(
            spotify_id="playlist-manage",
            name="Manage Me",
            track_count=3,
            tracks=[
                PlaylistTrack(
                    spotify_track_id="spotify-local",
                    position=0,
                    title="Local persisted title",
                    artist="Local persisted artist",
                ),
                PlaylistTrack(
                    spotify_track_id="spotify-missing",
                    position=1,
                    title="Missing",
                    artist="Artist",
                ),
                PlaylistTrack(
                    spotify_track_id="spotify-undownloaded",
                    position=2,
                    title="Not downloaded",
                    artist="Artist",
                ),
            ],
        )
        db.add_all(
            [
                playlist,
                Song(
                    path="/music/local.mp3",
                    filename="local.mp3",
                    spotify_track_id="spotify-local",
                    title="Indexed title",
                    artist="Indexed artist",
                    availability_status="available",
                ),
                Song(
                    path="/music/missing.mp3",
                    filename="missing.mp3",
                    spotify_track_id="spotify-missing",
                    title="Missing",
                    artist="Artist",
                    availability_status="missing",
                ),
            ]
        )
        db.commit()

        payload = playlist_tracks(playlist.id, db)

        assert payload["name"] == "Manage Me"
        assert payload["track_count"] == 3
        assert payload["deletable_count"] == 1
        assert [track["position"] for track in payload["tracks"]] == [1, 2, 3]
        assert payload["tracks"][0]["title"] == "Indexed title"
        assert payload["tracks"][0]["selectable"] is True
        assert payload["tracks"][1]["availability"] == "missing"
        assert payload["tracks"][1]["selectable"] is False
        assert payload["tracks"][2]["availability"] == "not_in_library"
        assert payload["tracks"][2]["song_id"] is None
    finally:
        db.close()


def test_playlists_page_exposes_guarded_track_manager():
    response = TestClient(app).get("/playlists")

    assert response.status_code == 200
    assert 'id="playlist-tracks-dialog"' in response.text
    assert 'id="playlist-select-all"' in response.text
    assert 'id="playlist-delete-selected"' in response.text
    assert "/static/js/playlists.js?v=" in response.text
