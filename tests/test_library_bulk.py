from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from app.database.models import BulkOperationItem, Song
from app.database.session import SessionLocal
from app.services.library_bulk import LibraryBulkWorker, create_bulk_task


def _songs(db, root: Path, count: int = 2):
    songs = []
    for index in range(count):
        path = root / f"song-{index}.mp3"
        path.write_bytes(b"audio")
        song = Song(
            path=str(path.resolve()),
            filename=path.name,
            artist="Artist",
            title=f"Song {index}",
            availability_status="available",
            artwork_status="missing",
            download_source="filesystem",
        )
        db.add(song)
        songs.append(song)
    db.commit()
    return songs


def test_bulk_task_continues_after_item_failure(tmp_path, monkeypatch):
    with SessionLocal() as db:
        songs = _songs(db, tmp_path)
        task = create_bulk_task(
            db,
            operation="refresh_metadata",
            song_ids=[song.id for song in songs],
        )
        worker = LibraryBulkWorker()
        calls = 0

        def apply(*args):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("broken tag")
            return args[1].original_path

        monkeypatch.setattr(worker, "_apply", apply)
        worker.process_task(db, task)
        db.refresh(task)
        items = db.scalars(
            select(BulkOperationItem)
            .where(BulkOperationItem.task_id == task.id)
            .order_by(BulkOperationItem.id)
        ).all()

        assert task.status == "completed_with_errors"
        assert task.completed_items == 1
        assert task.failed_items == 1
        assert [item.status for item in items] == ["failed", "completed"]
        assert items[0].error == "The file operation failed"


def test_bulk_task_is_failed_when_every_item_fails(tmp_path, monkeypatch):
    with SessionLocal() as db:
        songs = _songs(db, tmp_path)
        task = create_bulk_task(db, operation="refresh_metadata", song_ids=[song.id for song in songs])
        worker = LibraryBulkWorker()
        monkeypatch.setattr(worker, "_apply", lambda *_args: (_ for _ in ()).throw(RuntimeError("secret raw payload")))

        worker.process_task(db, task)
        db.refresh(task)

        assert task.status == "failed"
        assert task.completed_items == 0
        assert task.failed_items == 2
        assert task.error_code == "FILE_OPERATION_FAILED"
        assert task.error_summary == "The file operation failed"


def test_bulk_move_preserves_song_identity_and_rejects_collisions(tmp_path, monkeypatch):
    music = tmp_path / "music"
    music.mkdir()
    with SessionLocal() as db:
        song = _songs(db, music, 1)[0]
        worker = LibraryBulkWorker()
        worker.settings = SimpleNamespace(music_path=str(music), download_path=str(tmp_path))
        monkeypatch.setattr(
            "app.services.library_bulk.index_file",
            lambda db, path, **kwargs: SimpleNamespace(song_id=song.id),
        )
        destination = music / "Moved" / song.filename
        original_id = song.id
        result = worker._move_and_reindex(db, song, Path(song.path), destination)
        db.commit()

        assert result == str(destination.resolve())
        assert db.get(Song, original_id).path == str(destination.resolve())
        assert destination.is_file()


def test_bulk_delete_retains_song_provenance_as_missing(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    with SessionLocal() as db:
        song = _songs(db, music, 1)[0]
        worker = LibraryBulkWorker()
        worker.settings = SimpleNamespace(music_path=str(music), download_path=str(tmp_path))
        task = create_bulk_task(db, operation="delete", song_ids=[song.id])
        item = db.scalar(
            select(BulkOperationItem).where(BulkOperationItem.task_id == task.id)
        )

        worker._apply(db, item, "delete", {}, None)
        db.commit()
        db.refresh(song)

        assert not Path(song.path).exists()
        assert song.availability_status == "missing"
        assert db.get(Song, song.id) is not None
