from datetime import datetime

from app.database.models import Song
from app.database.session import SessionLocal
from app.services.library_health import library_health


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

        assert task.task_type == "library_maintenance"
        assert task.status == "queued"
        assert task.operation_payload == '{"action": "refresh"}'
        assert task.total_items == 1
