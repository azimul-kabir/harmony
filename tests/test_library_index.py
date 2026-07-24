from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.models import Song
from app.services import library_scanner
from app.services import library_service


def _metadata(path: Path, title: str = "Indexed Song") -> dict:
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


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_index_file_is_incremental(tmp_path, monkeypatch):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"audio")
    calls = 0

    def fake_read_metadata(path):
        nonlocal calls
        calls += 1
        return _metadata(Path(path))

    monkeypatch.setattr(library_scanner, "read_metadata", fake_read_metadata)

    with _session() as db:
        first = library_scanner.index_file(db, audio)
        second = library_scanner.index_file(db, audio)

        assert first.status == "added"
        assert second.status == "unchanged"
        assert first.song_id == second.song_id
        assert calls == 1


def test_reindex_detects_modified_metadata(tmp_path, monkeypatch):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"audio")
    title = "Original"

    def fake_read_metadata(path):
        return _metadata(Path(path), title=title)

    monkeypatch.setattr(library_scanner, "read_metadata", fake_read_metadata)

    with _session() as db:
        library_scanner.index_file(db, audio)
        title = "Repaired"
        result = library_scanner.index_file(db, audio, force=True)
        song = db.scalar(select(Song))

        assert result.status == "updated"
        assert song.title == "Repaired"


def test_scan_marks_missing_files_without_deleting_index(tmp_path, monkeypatch):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(
        library_scanner,
        "read_metadata",
        lambda path: _metadata(Path(path)),
    )

    with _session() as db:
        library_scanner.scan_library(db, tmp_path)
        song_id = db.scalar(select(Song.id))
        audio.unlink()

        result = library_scanner.scan_library(db, tmp_path)
        song = db.get(Song, song_id)

        assert result.missing == 1
        assert song.availability_status == "missing"


def test_scan_commits_each_file_to_release_sqlite_writer(tmp_path, monkeypatch):
    for name in ("one.mp3", "two.mp3"):
        (tmp_path / name).write_bytes(b"audio")

    monkeypatch.setattr(
        library_scanner,
        "index_file",
        lambda db, file, **kwargs: library_scanner.IndexResult(
            path=str(file), status="unchanged"
        ),
    )

    with _session() as db:
        commits = 0
        immediate_reservations = 0
        real_commit = db.commit

        def count_statements(_conn, _cursor, statement, _parameters, _context, _many):
            nonlocal immediate_reservations
            if statement.strip().upper() == "BEGIN IMMEDIATE":
                immediate_reservations += 1

        event.listen(db.get_bind(), "before_cursor_execute", count_statements)

        def counting_commit():
            nonlocal commits
            commits += 1
            real_commit()

        monkeypatch.setattr(db, "commit", counting_commit)
        result = library_scanner.scan_library(db, tmp_path, force=True)

        assert result.discovered == 2
        assert commits >= 3  # once per file, then missing-file reconciliation
        assert immediate_reservations == 2


def test_index_library_file_rejects_paths_outside_configured_music_root(tmp_path, monkeypatch):
    music = tmp_path / "music"
    music.mkdir()
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"audio")
    monkeypatch.setattr(library_service, "settings", type("Settings", (), {"music_path": str(music)})())

    with _session() as db:
        try:
            library_service.index_library_file(db, str(outside))
        except ValueError as error:
            assert str(error) == "Path must remain inside the configured music folder"
        else:  # pragma: no cover - makes the containment guarantee explicit
            raise AssertionError("out-of-root file was indexed")
