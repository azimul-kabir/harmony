from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.time import utcnow_naive
from app.database.models import Playlist, Song
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
        monkeypatch.setattr(
            auto_playlists, "export_m3u", lambda db, playlist: len(playlist.tracks)
        )

        result = auto_playlists.generate(db, "recently-added", limit=3)

        playlist = db.scalar(
            select(Playlist).where(Playlist.smart_rule == "recently-added")
        )
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
        monkeypatch.setattr(
            auto_playlists, "export_m3u", lambda db, playlist: len(playlist.tracks)
        )

        auto_playlists.generate(db, "recently-downloaded")

        playlist = db.scalar(
            select(Playlist).where(Playlist.smart_rule == "recently-downloaded")
        )
        assert [track.spotify_track_id for track in playlist.tracks] == ["track-2"]


def test_playback_dependent_playlists_use_cached_navidrome_stats(monkeypatch):
    with SessionLocal() as db:
        favorite = _song(db, 1, age_days=100)
        favorite.navidrome_play_count = 8
        favorite.navidrome_starred_at = utcnow_naive() - timedelta(days=90)
        favorite.navidrome_last_played_at = utcnow_naive() - timedelta(days=60)
        popular = _song(db, 2)
        popular.navidrome_play_count = 20
        db.commit()
        monkeypatch.setattr(
            auto_playlists, "export_m3u", lambda db, playlist: len(playlist.tracks)
        )

        assert auto_playlists.generate(db, "most-played")["track_count"] == 2
        playlist = db.scalar(
            select(Playlist).where(Playlist.smart_rule == "most-played")
        )
        assert [track.spotify_track_id for track in playlist.tracks] == [
            "track-2",
            "track-1",
        ]
        assert auto_playlists.generate(db, "favorites")["track_count"] == 1


def test_definition_status_reports_generated_settings(monkeypatch):
    with SessionLocal() as db:
        _song(db, 1, source="spotify")
        db.commit()
        monkeypatch.setattr(auto_playlists, "export_m3u", lambda db, playlist: 1)
        auto_playlists.generate(db, "recently-added", limit=25)

        status = {item["id"]: item for item in auto_playlists.definitions(db)}

        assert status["recently-added"]["enabled"] is True
        assert status["recently-added"]["limit"] == 25
        assert status["favorites"]["available"] is True


def test_update_navidrome_stats_matches_path_and_caches_signals():
    with SessionLocal() as db:
        song = _song(db, 7)
        db.commit()

        count = auto_playlists.update_navidrome_stats(
            db,
            [
                {
                    "id": "nav-7",
                    "path": "music/song-7.mp3",
                    "playCount": 4,
                    "played": "2026-07-01T12:00:00Z",
                    "starred": "2026-06-01T12:00:00Z",
                }
            ],
        )

        db.refresh(song)
        assert count == 1
        assert song.navidrome_id == "nav-7"
        assert song.navidrome_play_count == 4
        assert song.navidrome_last_played_at == datetime(2026, 7, 1, 12)


def test_refresh_enabled_regenerates_only_enabled_auto_playlists(monkeypatch):
    with SessionLocal() as db:
        _song(db, 1, source="spotify")
        db.commit()
        monkeypatch.setattr(
            auto_playlists, "export_m3u", lambda db, playlist: len(playlist.tracks)
        )
        auto_playlists.generate(db, "recently-added", limit=12)
        auto_playlists.generate(db, "recently-downloaded", limit=8, enabled=False)

        refreshed = auto_playlists.refresh_enabled(db)

        assert refreshed == 1
        status = {item["id"]: item for item in auto_playlists.definitions(db)}
        assert status["recently-added"]["limit"] == 12
        assert status["recently-downloaded"]["enabled"] is False
