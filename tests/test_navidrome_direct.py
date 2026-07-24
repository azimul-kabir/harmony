import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.database.models import Playlist, PlaylistTrack, Song
from app.database.session import SessionLocal
from app.services.navidrome_direct import (
    NavidromeDirectPlaylistSync,
    NavidromeDirectSyncError,
    select_song_match,
)


def _settings():
    return SimpleNamespace(
        navidrome_direct_search_limit=25,
        navidrome_direct_duration_tolerance_seconds=5,
    )


def _song(path, **overrides):
    values = {
        "path": str(path),
        "filename": Path(path).name,
        "title": "Superstition",
        "artist": "Stevie Wonder",
        "album": "Talking Book",
        "duration": 244,
    }
    values.update(overrides)
    return Song(**values)


def test_song_match_rejects_equal_best_candidates(tmp_path):
    song = _song(tmp_path / "Superstition.mp3")
    candidates = [
        {
            "id": "one",
            "title": "Superstition",
            "artist": "Stevie Wonder",
            "album": "Talking Book",
            "duration": 244,
        },
        {
            "id": "two",
            "title": "Superstition",
            "artist": "Stevie Wonder",
            "album": "Talking Book",
            "duration": 244,
        },
    ]

    assert select_song_match(song, candidates) is None


def test_direct_sync_creates_and_verifies_original_order(tmp_path):
    first_path = tmp_path / "first.mp3"
    second_path = tmp_path / "second.mp3"
    first_path.touch()
    second_path.touch()

    db = SessionLocal()
    try:
        playlist = Playlist(
            spotify_id="ordered-playlist",
            name="Ordered Playlist",
            track_count=2,
            tracks=[
                PlaylistTrack(
                    spotify_track_id="spotify-two",
                    position=0,
                    title="Second",
                    artist="Artist",
                ),
                PlaylistTrack(
                    spotify_track_id="spotify-one",
                    position=1,
                    title="First",
                    artist="Artist",
                ),
            ],
        )
        db.add_all(
            [
                playlist,
                _song(
                    first_path,
                    spotify_track_id="spotify-one",
                    navidrome_id="nav-one",
                    title="First",
                    artist="Artist",
                    album="Album",
                ),
                _song(
                    second_path,
                    spotify_track_id="spotify-two",
                    navidrome_id="nav-two",
                    title="Second",
                    artist="Artist",
                    album="Album",
                ),
            ]
        )
        db.commit()
        playlist_id = playlist.id
    finally:
        db.close()

    class Client:
        replaced_ids = None

        async def get_song(self, song_id):
            title = "First" if song_id == "nav-one" else "Second"
            return {
                "id": song_id,
                "title": title,
                "artist": "Artist",
                "album": "Album",
                "duration": 244,
            }

        async def get_playlists(self):
            return []

        async def replace_playlist(
            self, *, name, song_ids, playlist_id=None
        ):
            assert name == "Ordered Playlist"
            assert playlist_id is None
            self.replaced_ids = list(song_ids)
            return {"id": "nav-playlist"}

        async def get_playlist(self, playlist_id):
            assert playlist_id == "nav-playlist"
            return {
                "id": playlist_id,
                "entry": [
                    {"id": song_id} for song_id in self.replaced_ids
                ],
            }

    client = Client()
    result = asyncio.run(
        NavidromeDirectPlaylistSync(
            settings=_settings(), client=client
        ).reconcile(playlist_id)
    )

    assert client.replaced_ids == ["nav-two", "nav-one"]
    assert result.track_count == 2
    db = SessionLocal()
    try:
        playlist = db.get(Playlist, playlist_id)
        assert playlist.navidrome_playlist_id == "nav-playlist"
        assert playlist.navidrome_sync_status == "synced"
        assert playlist.navidrome_synced_track_count == 2
    finally:
        db.close()


def test_direct_sync_refuses_readonly_same_name_playlist(tmp_path):
    song_path = tmp_path / "song.mp3"
    song_path.touch()
    db = SessionLocal()
    try:
        playlist = Playlist(
            spotify_id="readonly-playlist",
            name="Imported",
            track_count=1,
            tracks=[
                PlaylistTrack(
                    spotify_track_id="spotify-song",
                    position=0,
                    title="Song",
                    artist="Artist",
                )
            ],
        )
        db.add_all(
            [
                playlist,
                _song(
                    song_path,
                    spotify_track_id="spotify-song",
                    navidrome_id="nav-song",
                    title="Song",
                    artist="Artist",
                    album="Album",
                ),
            ]
        )
        db.commit()
        playlist_id = playlist.id
    finally:
        db.close()

    class Client:
        async def get_song(self, song_id):
            return {
                "id": song_id,
                "title": "Song",
                "artist": "Artist",
                "album": "Album",
                "duration": 244,
            }

        async def get_playlists(self):
            return [{"id": "readonly", "name": "Imported", "readonly": True}]

    with pytest.raises(NavidromeDirectSyncError, match="read-only"):
        asyncio.run(
            NavidromeDirectPlaylistSync(
                settings=_settings(), client=Client()
            ).reconcile(playlist_id)
        )

    db = SessionLocal()
    try:
        playlist = db.get(Playlist, playlist_id)
        assert playlist.navidrome_sync_status == "fallback"
        assert "read-only" in playlist.navidrome_sync_error
    finally:
        db.close()
