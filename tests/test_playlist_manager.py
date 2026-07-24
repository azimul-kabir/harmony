from types import SimpleNamespace

from app.database.models import Playlist, PlaylistTrack, Song
from app.database.session import SessionLocal
from app.services import playlist_manager


def _playlist(db, *, spotify_id: str, name: str, track_id: str) -> Playlist:
    playlist = Playlist(
        spotify_id=spotify_id,
        name=name,
        track_count=1,
    )
    db.add(playlist)
    db.flush()
    db.add(
        PlaylistTrack(
            playlist_id=playlist.id,
            spotify_track_id=track_id,
            position=1,
            title="Stored title",
            artist="Stored artist",
            album="Stored album",
            album_artist="Stored artist",
            track_number=3,
            duration=123,
        )
    )
    db.commit()
    db.refresh(playlist)
    return playlist


def test_export_uses_persisted_metadata_and_only_writes_existing_files(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        playlist_manager,
        "get_settings",
        lambda: SimpleNamespace(music_path=str(tmp_path)),
    )
    expected = tmp_path / "Stored artist" / "Stored album" / "03 - Stored title.mp3"
    expected.parent.mkdir(parents=True)
    expected.write_bytes(b"audio")

    db = SessionLocal()
    try:
        playlist = _playlist(
            db,
            spotify_id="playlist-1",
            name="Reliable",
            track_id="track-1",
        )

        assert playlist_manager.export_m3u(db, playlist) == 1

        content = (tmp_path / "Playlists" / "Reliable.m3u").read_text()
        assert "#EXTINF:123,Stored artist - Stored title" in content
        assert "../Stored artist/Stored album/03 - Stored title.mp3" in content

        expected.unlink()
        assert playlist_manager.export_m3u(db, playlist) == 0
        assert (
            tmp_path / "Playlists" / "Reliable.m3u"
        ).read_text() == "#EXTM3U\n"
    finally:
        db.close()


def test_completed_track_refreshes_only_containing_playlists(monkeypatch):
    db = SessionLocal()
    try:
        affected = _playlist(
            db,
            spotify_id="playlist-1",
            name="Affected",
            track_id="track-1",
        )
        _playlist(
            db,
            spotify_id="playlist-2",
            name="Unrelated",
            track_id="track-2",
        )
        exported = []
        monkeypatch.setattr(
            playlist_manager,
            "export_m3u",
            lambda session, playlist: exported.append(playlist.id) or 1,
        )

        assert playlist_manager.export_m3us_for_track(db, "track-1") == 1
        assert exported == [affected.id]
    finally:
        db.close()


def test_export_prefers_indexed_song_path(monkeypatch, tmp_path):
    monkeypatch.setattr(
        playlist_manager,
        "get_settings",
        lambda: SimpleNamespace(music_path=str(tmp_path)),
    )
    actual = tmp_path / "Different Artist" / "Different Album" / "song.mp3"
    actual.parent.mkdir(parents=True)
    actual.write_bytes(b"audio")

    db = SessionLocal()
    try:
        playlist = _playlist(
            db,
            spotify_id="playlist-1",
            name="Indexed",
            track_id="track-1",
        )
        db.add(
            Song(
                path=str(actual),
                filename=actual.name,
                artist="Indexed artist",
                title="Indexed title",
                duration=222,
                spotify_track_id="track-1",
            )
        )
        db.commit()

        assert playlist_manager.export_m3u(db, playlist) == 1
        content = (tmp_path / "Playlists" / "Indexed.m3u").read_text()
        assert "#EXTINF:222,Indexed artist - Indexed title" in content
        assert "../Different Artist/Different Album/song.mp3" in content
    finally:
        db.close()
