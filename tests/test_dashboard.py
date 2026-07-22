from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.base import Base
from datetime import UTC, datetime

from app.database.models import (
    DownloadJob,
    MetadataSuggestion,
    Playlist,
    Song,
    SyncSource,
    Task,
)
from app.domain.download import JobStatus
from app.domain.task import TaskStatus, TaskType
from app.services.dashboard import get_dashboard_snapshot, get_dashboard_stats
from app.services.library_analytics import library_analytics


def test_dashboard_song_count_matches_available_library_songs():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                Song(
                    path="/music/available.mp3",
                    filename="available.mp3",
                    availability_status="available",
                ),
                Song(
                    path="/music/missing.mp3",
                    filename="missing.mp3",
                    availability_status="missing",
                ),
            ]
        )
        db.commit()

        assert get_dashboard_stats(db)["songs"] == 1
        assert (
            get_dashboard_stats(db)["songs"] == library_analytics.calculate(db)["songs"]
        )


def test_dashboard_snapshot_contains_actionable_queue_and_library_summaries():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC).replace(tzinfo=None)
    with Session(engine) as db:
        db.add_all(
            [
                Song(
                    path="/music/ready.mp3",
                    filename="ready.mp3",
                    artist="Artist",
                    album="Album",
                    artwork_status="missing",
                    genre="Rock",
                    bitrate=320000,
                    duration=245,
                ),
                Song(
                    path="/music/lost.mp3",
                    filename="lost.mp3",
                    availability_status="missing",
                ),
                DownloadJob(
                    spotify_url="spotify:track:running",
                    title="Running",
                    artist="Artist",
                    status=JobStatus.RUNNING.value,
                ),
                DownloadJob(
                    spotify_url="spotify:track:queued",
                    title="Queued",
                    artist="Artist",
                    status=JobStatus.QUEUED.value,
                ),
                DownloadJob(
                    spotify_url="spotify:track:failed",
                    title="Failed",
                    artist="Artist",
                    status=JobStatus.FAILED.value,
                ),
                DownloadJob(
                    spotify_url="spotify:track:complete",
                    title="Complete",
                    artist="Artist",
                    status=JobStatus.COMPLETED.value,
                    completed_at=now,
                ),
                Playlist(spotify_id="playlist", name="Playlist"),
                SyncSource(
                    type="playlist",
                    spotify_id="source",
                    spotify_url="https://example.test/source",
                    name="Source",
                ),
                MetadataSuggestion(
                    entity_type="song",
                    entity_id=1,
                    field_name="genre",
                    provider="musicbrainz",
                    confidence_level="high",
                    status="pending",
                ),
                Task(
                    name="Refresh Library",
                    spotify_url="library://maintenance/refresh",
                    task_type=TaskType.LIBRARY_MAINTENANCE.value,
                    status=TaskStatus.COMPLETED_WITH_ERRORS.value,
                    total_items=3,
                    completed_items=2,
                    failed_items=1,
                    error_code="INDEX_ERROR",
                    completed_at=now,
                ),
            ]
        )
        db.commit()

        snapshot = get_dashboard_snapshot(db)

        assert snapshot["kpis"] == {
            "songs": 1,
            "albums": 1,
            "artists": 1,
            "sources": 1,
            "playlists": 1,
            "storage_bytes": 0,
            "health_score": 50,
            "failed_jobs": 1,
        }
        assert snapshot["downloads"] == {
            "running": 1,
            "queued": 1,
            "failed": 1,
            "completed_today": 1,
        }
        assert snapshot["health"] == {
            "score": 50,
            "missing_artwork": 1,
            "missing_metadata": 1,
            "missing_files": 1,
            "pending_suggestions": 1,
        }
        assert snapshot["analytics"] == {
            "genres": 1,
            "average_bitrate": 320000,
            "average_duration": 245.0,
            "recently_added": 1,
            "largest_album": {
                "name": "Album",
                "artist": "Artist",
                "song_count": 1,
                "storage_bytes": 0,
                "year": None,
            },
            "newest_album": None,
            "oldest_album": None,
        }
        assert snapshot["maintenance"] == [{
            "id": 1,
            "name": "Refresh Library",
            "status": "completed_with_errors",
            "completed": 2,
            "failed": 1,
            "skipped": 0,
            "total": 3,
            "error_code": "INDEX_ERROR",
        }]
        assert [item["id"] for item in snapshot["collections"]] == [
            "recently-added",
            "missing-artwork",
            "missing-metadata",
            "highest-bitrate",
            "large-albums",
        ]
