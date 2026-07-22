"""Durable canonical metadata application lifecycle coverage.

These tests exercise the worker directly: submission must only reserve work,
while canonical writes, history, and derived-index work occur in the worker.
"""

from sqlalchemy import select

from app.database.models import (MetadataApplicationBatch, MetadataApplicationLock,
    MetadataHistory, MetadataSuggestion, Song, Task)
from app.database.session import SessionLocal
from app.domain.task import TaskStatus
from app.services.metadata_intelligence import metadata_application_service, metadata_service
from app.services.task_service import cancel_task, recover_library_jobs


def _accepted_title(db, song, title):
    suggestion = metadata_service.create_suggestion(
        db, entity_type="song", entity_id=song.id, field_name="title",
        suggested_value=title, provider="test", confidence_level="high",
        confidence=0.95,
    )
    metadata_service.accept_suggestion(db, suggestion.id, reviewed_by="test")
    db.commit()
    return suggestion


def _song(db, title="Original"):
    song = Song(path=f"/music/{title}.mp3", filename=f"{title}.mp3", title=title,
                artist="Artist", album="Album", availability_status="available")
    db.add(song)
    db.commit()
    return song


def test_submission_reserves_work_without_inline_canonical_write():
    with SessionLocal() as db:
        song = _song(db)
        suggestion = _accepted_title(db, song, "Applied later")

        queued = metadata_application_service.submit(db, [song.id], suggestion_ids=[suggestion.id])

        db.refresh(song)
        task = db.get(Task, queued["job_id"])
        batch = db.get(MetadataApplicationBatch, queued["batch_id"])
        assert song.title == "Original"
        assert task.status == TaskStatus.QUEUED.value
        assert batch.status == "queued" and batch.job_id == task.id
        assert db.scalar(select(MetadataApplicationLock.task_id).where(
            MetadataApplicationLock.song_id == song.id)) == task.id
        assert db.scalars(select(MetadataHistory).where(MetadataHistory.entity_id == song.id)).all() == []


def test_worker_applies_selected_field_then_rolls_it_back_immutably():
    with SessionLocal() as db:
        song = _song(db)
        title = _accepted_title(db, song, "Worker title")
        artist = metadata_service.create_suggestion(
            db, entity_type="song", entity_id=song.id, field_name="artist",
            suggested_value="Different artist", provider="test", confidence_level="high")
        metadata_service.accept_suggestion(db, artist.id, reviewed_by="test")
        db.commit()
        queued = metadata_application_service.submit(db, [song.id], suggestion_ids=[title.id])
        task = db.get(Task, queued["job_id"])

        metadata_application_service.process_task(db, task)
        db.refresh(song); db.refresh(title); db.refresh(artist)
        batch = db.get(MetadataApplicationBatch, queued["batch_id"])
        history = db.scalar(select(MetadataHistory).where(MetadataHistory.suggestion_id == title.id))
        assert (song.title, song.artist, title.status, artist.status) == ("Worker title", "Artist", "applied", "accepted")
        assert task.status == TaskStatus.COMPLETED.value
        assert (batch.status, batch.applied_fields, history.audio_file_modified) == ("completed", 1, False)
        assert db.scalars(select(MetadataApplicationLock)).all() == []

        rollback = metadata_application_service.submit(db, [song.id], rollback_history_ids=[history.id])
        rollback_task = db.get(Task, rollback["job_id"])
        metadata_application_service.process_task(db, rollback_task)
        reversal = db.scalar(select(MetadataHistory).where(MetadataHistory.reversal_of_history_id == history.id))
        rollback_batch = db.get(MetadataApplicationBatch, rollback["batch_id"])
        db.refresh(song)
        assert song.title == "Original"
        assert history.new_value == '"Worker title"'
        assert reversal is not None and reversal.audio_file_modified is False
        assert rollback_task.status == TaskStatus.COMPLETED.value and rollback_batch.status == "rolled_back"
        assert db.scalars(select(MetadataApplicationLock)).all() == []


def test_queued_cancellation_and_restart_recovery_release_reservations():
    with SessionLocal() as db:
        song = _song(db)
        suggestion = _accepted_title(db, song, "Never applied")
        queued = metadata_application_service.submit(db, [song.id], suggestion_ids=[suggestion.id])
        task = db.get(Task, queued["job_id"])
        cancel_task(db, task)
        batch = db.get(MetadataApplicationBatch, queued["batch_id"])
        db.refresh(song)
        assert (task.status, batch.status, song.title) == (TaskStatus.CANCELLED.value, "cancelled", "Original")
        assert db.scalars(select(MetadataApplicationLock)).all() == []

        resumed = metadata_application_service.submit(db, [song.id], suggestion_ids=[suggestion.id])
        task = db.get(Task, resumed["job_id"])
        task.status = TaskStatus.RUNNING.value
        db.commit()
        assert recover_library_jobs(db) >= 1
        batch = db.get(MetadataApplicationBatch, resumed["batch_id"])
        db.refresh(task); db.refresh(song)
        assert (task.status, batch.status, song.title) == (TaskStatus.INTERRUPTED.value, "interrupted", "Original")
        assert db.scalars(select(MetadataApplicationLock)).all() == []
