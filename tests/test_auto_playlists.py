from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.time import utcnow_naive
from app.database.models import Playlist, PlaylistTrack, Song
from app.database.session import SessionLocal
from app.services import auto_playlists


def _song(db, index: int, *, source: str = "filesystem", age_days: int = 0):
    song = Song(
        path=f"/music/song-{index}.mp3",
        filename=f"song-{index}.mp3",
        title=f"Song {index}",
        artist="Artist",
        album="Album",
        spotify_track_id=f"track-{index}",
        download_source=source,
        availability_status="available",
        created_at=utcnow_naive() - timedelta(days=age_days, minutes=index),
    )
    db.add(song)
    return song


def test_recently_added_generates_capped_durable_playlist(monkeypatch):
    with SessionLocal() as db:
        for index in range(4):
            _song(db, index, source="youtube_music")
        db.commit()
        monkeypatch.setattr(auto_playlists, "export_m3u", lambda db, playlist: len(playlist.tracks))

        result = auto_playlists.generate(db, "recently-added", limit=3)

        playlist = db.scalar(select(Playlist).where(Playlist.smart_rule == "recently-added"))
        assert result["track_count"] == 3
        assert playlist is not None
        assert playlist.playlist_kind == "smart"
        assert playlist.smart_limit == 3
        assert [track.spotify_track_id for track in playlist.tracks] == [
            "track-0",
            "track-1",
            "track-2",
        ]


def test_recently_downloaded_excludes_filesystem_imports(monkeypatch):
    with SessionLocal() as db:
        _song(db, 1, source="filesystem")
        _song(db, 2, source="spotify")
        db.commit()
        monkeypatch.setattr(auto_playlists, "export_m3u", lambda db, playlist: len(playlist.tracks))

        auto_playlists.generate(db, "recently-downloaded")

        playlist = db.scalar(select(Playlist).where(Playlist.smart_rule == "recently-downloaded"))
        assert [track.spotify_track_id for track in playlist.tracks] == ["track-2"]


def test_playback_dependent_definition_fails_cleanly():
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="Navidrome play counts"):
            auto_playlists.generate(db, "most-played")


def test_definition_status_reports_generated_settings(monkeypatch):
    with SessionLocal() as db:
        _song(db, 1, source="spotify")
        db.commit()
        monkeypatch.setattr(auto_playlists, "export_m3u", lambda db, playlist: 1)
        auto_playlists.generate(db, "recently-added", limit=25)

        status = {item["id"]: item for item in auto_playlists.definitions(db)}

        assert status["recently-added"]["enabled"] is True
        assert status["recently-added"]["limit"] == 25
        assert status["favorites"]["available"] is False


def test_refresh_enabled_regenerates_only_enabled_auto_playlists(monkeypatch):
    with SessionLocal() as db:
        _song(db, 1, source="spotify")
        db.commit()
        monkeypatch.setattr(auto_playlists, "export_m3u", lambda db, playlist: len(playlist.tracks))
        auto_playlists.generate(db, "recently-added", limit=12)
        auto_playlists.generate(db, "recently-downloaded", limit=8, enabled=False)

        refreshed = auto_playlists.refresh_enabled(db)

        assert refreshed == 1
        status = {item["id"]: item for item in auto_playlists.definitions(db)}
        assert status["recently-added"]["limit"] == 12
        assert status["recently-downloaded"]["enabled"] is False
