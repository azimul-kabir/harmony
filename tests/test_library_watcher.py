from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.models import Song
from app.services import library_scanner, library_watcher
from app.services.library_watcher import (
    LibraryWatcher,
    PendingFileEvent,
    _coalesce,
    _observer_is_healthy,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _metadata(path: Path, title: str = "Renamed Song") -> dict:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "filename": path.name,
        "artist": "Artist",
        "album_artist": "Artist",
        "album": "Album",
        "title": title,
        "spotify_track_id": None,
        "spotify_album_id": None,
        "musicbrainz_recording_id": None,
        "isrc": None,
        "track": 1,
        "disc": 1,
        "year": 2026,
        "genre": "Rock",
        "duration": 180.0,
        "bitrate": 320000,
        "codec": "mp3",
        "sample_rate": 44100,
        "file_size": stat.st_size,
        "modified_time": int(stat.st_mtime),
        "artwork_status": "missing",
        "metadata_hash": title,
    }


def test_rename_preserves_internal_song_id(tmp_path, monkeypatch):
    old_path = tmp_path / "old.mp3"
    new_path = tmp_path / "new.mp3"
    new_path.write_bytes(b"audio")
    monkeypatch.setattr(
        library_scanner,
        "read_metadata",
        lambda path: _metadata(Path(path)),
    )

    with _session() as db:
        song = Song(path=str(old_path.resolve()), filename=old_path.name)
        db.add(song)
        db.commit()
        song_id = song.id

        watcher = LibraryWatcher(root=tmp_path)
        watcher._apply_move(
            db,
            PendingFileEvent(
                kind="moved",
                source=str(old_path.resolve()),
                destination=str(new_path.resolve()),
            ),
        )

        db.expire_all()
        renamed = db.get(Song, song_id)
        assert renamed.path == str(new_path.resolve())
        assert renamed.filename == "new.mp3"
        assert renamed.title == "Renamed Song"


def test_processing_recovers_from_transient_failure(tmp_path, monkeypatch):
    watcher = LibraryWatcher(root=tmp_path, retry_delays=(0.0, 0.0))
    attempts = 0

    def flaky_apply(event):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("file is still being written")

    monkeypatch.setattr(watcher, "_apply", flaky_apply)
    watcher._process_with_recovery(
        PendingFileEvent(kind="created", source=str(tmp_path / "song.mp3"))
    )

    assert attempts == 3


def test_non_audio_paths_are_ignored():
    assert library_watcher._is_audio_path("track.flac")
    assert not library_watcher._is_audio_path("cover.jpg")


def test_coalescing_preserves_created_and_moved_semantics():
    created = PendingFileEvent(kind="created", source="/music/song.mp3")
    modified = PendingFileEvent(kind="modified", source="/music/song.mp3")
    moved = PendingFileEvent(
        kind="moved",
        source="/music/old.mp3",
        destination="/music/song.mp3",
    )

    assert _coalesce(created, modified) is created
    assert _coalesce(moved, modified) is moved


def test_observer_health_includes_native_emitter_threads():
    alive = type("Emitter", (), {"is_alive": lambda self: True})()
    stopped = type("Emitter", (), {"is_alive": lambda self: False})()
    observer = type(
        "Observer",
        (),
        {"is_alive": lambda self: True, "emitters": [alive, stopped]},
    )()

    assert not _observer_is_healthy(observer)


def test_watcher_ignores_events_resolving_outside_music_root(tmp_path, monkeypatch):
    music = tmp_path / "music"
    music.mkdir()
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"audio")
    watcher = LibraryWatcher(root=music)
    called = False

    def unexpected_session():
        nonlocal called
        called = True
        raise AssertionError("out-of-root watcher event opened a database session")

    monkeypatch.setattr(library_watcher, "SessionLocal", unexpected_session)
    watcher._apply(PendingFileEvent(kind="created", source=str(outside)))
    assert not called
