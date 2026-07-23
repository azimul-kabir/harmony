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
            Song(
                path="/health/gone.flac",
                filename="gone.flac",
                title="Gone",
                artist="Artist",
                album="Album",
                file_size=50,
                artwork_status="embedded",
                availability_status="missing",
                download_source="filesystem",
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
        assert health["health_score"] == 67
        assert health["last_updated"] == datetime(2026, 7, 21, 5, 0)
        assert health["checks"][-1]["available"] is False
        missing_files = next(check for check in health["checks"] if check["id"] == "missing-files")
        assert missing_files == {
            "id": "missing-files",
            "label": "Missing indexed files",
            "count": 1,
            "status": "attention",
            "available": True,
        }


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


def test_health_issue_records_identify_song_and_hide_absolute_paths():
    with SessionLocal() as db:
        db.add(Song(path="/private/music/Queen/03.flac", filename="03.flac", title=None,
                    artist="Queen", album="A Night at the Opera", availability_status="available"))
        db.add(Song(path="/private/music/gone.flac", filename="gone.flac", title="Gone",
                    artist=None, album=None, availability_status="missing"))
        db.commit()

        metadata = library_health.issues(db, "metadata")
        missing = library_health.issues(db, "missing-files")

        assert metadata["items"][0]["entity_id"]
        assert metadata["items"][0]["artist"] == "Queen"
        assert metadata["items"][0]["album"] == "A Night at the Opera"
        assert metadata["items"][0]["filename"] == "03.flac"
        assert "/private" not in str(metadata["items"][0])
        assert missing["items"][0]["title"] == "Gone"
        assert missing["items"][0]["artist"] == "Unknown artist"
        assert missing["items"][0]["availability"] == "missing"


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


def test_health_issues_include_safe_song_identity_and_exclude_stale_records():
    with SessionLocal() as db:
        available = Song(
            path="/private/music/Queen/unknown.flac", filename="unknown.flac", title=None,
            artist="Queen", album="A Night at the Opera", track=3, disc=1,
            availability_status="available",
        )
        missing = Song(
            path="/private/music/gone.flac", filename="gone.flac", title="Gone",
            artist="Artist", album="Album", availability_status="missing",
        )
        db.add_all([available, missing])
        db.commit()

        metadata = library_health.issues(db, "metadata")
        missing_files = library_health.issues(db, "missing-files")

        assert metadata["total"] == 1
        issue = metadata["items"][0]
        assert issue["entity_id"] == available.id
        assert issue["title"] == "unknown.flac"
        assert issue["artist"] == "Queen"
        assert issue["album"] == "A Night at the Opera"
        assert issue["field"] == "title"
        assert issue["filename"] == "unknown.flac"
        assert "/private/music" not in str(issue)
        assert missing_files["items"][0]["entity_id"] == missing.id
        assert missing_files["items"][0]["availability"] == "missing"
