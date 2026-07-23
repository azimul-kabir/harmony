from datetime import datetime

from app.database.models import Song
from app.database.session import SessionLocal
from app.services.library_health import LibraryMaintenanceWorker, library_health


def test_health_snapshot_reports_completeness_and_future_duplicates():
    with SessionLocal() as db:
        db.query(Song).delete()
        db.add_all([
            Song(
                path="/health/complete.flac",
                filename="complete.flac",
                title="Complete",
                artist="Artist",
                album="Album",
                file_size=100,
                artwork_status="embedded",
                availability_status="available",
                download_source="filesystem",
                last_indexed_at=datetime(2026, 7, 21, 4, 0),
            ),
            Song(
                path="/health/incomplete.flac",
                filename="incomplete.flac",
                title=None,
                artist="Artist",
                album="Album",
                file_size=200,
                artwork_status="missing",
                availability_status="available",
                download_source="filesystem",
                last_indexed_at=datetime(2026, 7, 21, 5, 0),
            ),
        ])
        db.commit()

        health = library_health.calculate(db)

        assert health["songs"] == 2
        assert health["albums"] == 1
        assert health["artists"] == 1
        assert health["storage_bytes"] == 300
        assert health["missing_artwork"] == 1
        assert health["missing_metadata"] == 1
        assert health["duplicates"] is None
        assert health["health_score"] == 60
        assert health["last_updated"] == datetime(2026, 7, 21, 5, 0)
        assert health["checks"][2]["available"] is False


def test_health_action_uses_durable_task_system():
    with SessionLocal() as db:
        task = library_health.create_action(db, "refresh")
        task_id = task.id
        db.expire_all()
        persisted = db.get(type(task), task_id)

        assert persisted.task_type == "library_maintenance"
        assert persisted.status == "queued"
        assert persisted.operation_payload == '{"action": "refresh"}'
        assert persisted.total_items == 1


def test_rebuild_task_keeps_completed_progress_after_index_scan_commits(monkeypatch):
    def scan_and_commit(db, *_args, **_kwargs):
        # scan_library commits the index transaction, which expires ORM state.
        db.commit()

    monkeypatch.setattr("app.services.library_health.scan_library", scan_and_commit)
    monkeypatch.setattr("app.services.library_health.library_search.rebuild", lambda _db: 0)

    with SessionLocal() as db:
        task = library_health.create_action(db, "rebuild")

        LibraryMaintenanceWorker().process_task(db, task)
        persisted = db.get(type(task), task.id)

        assert persisted.status == "completed"
        assert persisted.completed_items == persisted.total_items == 1
