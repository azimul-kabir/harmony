from fastapi.testclient import TestClient

from app.api import playlist as playlist_api
from app.api.playlist import delete_playlist, playlist_tracks
from app.database.models import (
    DownloadJob,
    Playlist,
    PlaylistTrack,
    Song,
    SyncSource,
)
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
                    cover_url="https://images.example/local.jpg",
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
                DownloadJob(
                    spotify_url=(
                        "https://open.spotify.com/track/"
                        "spotify-undownloaded"
                    ),
                    spotify_track_id="spotify-undownloaded",
                    title="Not downloaded",
                    artist="Artist",
                    cover_url="https://images.example/pending.jpg",
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
        assert payload["tracks"][0]["cover_url"] == (
            "https://images.example/local.jpg"
        )
        assert payload["tracks"][0]["selectable"] is True
        assert payload["tracks"][1]["availability"] == "missing"
        assert payload["tracks"][1]["selectable"] is False
        assert payload["tracks"][2]["availability"] == "not_in_library"
        assert payload["tracks"][2]["song_id"] is None
        assert payload["tracks"][2]["cover_url"] == (
            "https://images.example/pending.jpg"
        )
    finally:
        db.close()


def test_playlists_page_exposes_guarded_track_manager():
    response = TestClient(app).get("/playlists")

    assert response.status_code == 200
    assert 'id="playlist-tracks-dialog"' in response.text
    assert 'id="playlist-select-all"' in response.text
    assert 'id="playlist-delete-selected"' in response.text
    assert "/static/js/playlists.js?v=" in response.text


def test_delete_playlist_removes_record_and_m3u_but_keeps_songs_and_source(
    tmp_path, monkeypatch
):
    m3u = tmp_path / "Delete Me.m3u"
    m3u.write_text("#EXTM3U\nsong.mp3\n", encoding="utf-8")
    monkeypatch.setattr(
        playlist_api,
        "playlist_file_path",
        lambda name: m3u,
    )
    db = SessionLocal()
    try:
        source = SyncSource(
            type="playlist",
            spotify_id="delete-playlist",
            spotify_url="https://open.spotify.com/playlist/delete-playlist",
            name="Delete Me",
        )
        song = Song(
            path=str(tmp_path / "song.mp3"),
            filename="song.mp3",
            spotify_track_id="delete-song",
            title="Keep Me",
        )
        playlist = Playlist(
            spotify_id="delete-playlist",
            name="Delete Me",
            track_count=1,
            tracks=[
                PlaylistTrack(
                    spotify_track_id="delete-song",
                    position=0,
                    title="Keep Me",
                )
            ],
        )
        db.add_all([source, song, playlist])
        db.commit()
        playlist_id = playlist.id
        song_id = song.id
        source_id = source.id

        result = delete_playlist(playlist_id, db)

        assert result["message"] == (
            "Playlist deleted. Library songs were not removed."
        )
        assert db.get(Playlist, playlist_id) is None
        assert db.get(Song, song_id) is not None
        assert db.get(SyncSource, source_id) is not None
        assert m3u.exists() is False
    finally:
        db.close()


def test_playlist_card_exposes_delete_action():
    db = SessionLocal()
    try:
        db.add(
            Playlist(
                spotify_id="visible-delete",
                name="Visible Delete",
                track_count=0,
            )
        )
        db.commit()
    finally:
        db.close()

    response = TestClient(app).get("/playlists")

    assert response.status_code == 200
    assert 'class="btn-secondary playlist-delete-btn"' in response.text
    assert 'data-playlist-name="Visible Delete"' in response.text
