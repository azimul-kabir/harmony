from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.database.base import Base
from datetime import UTC, datetime

from app.database.models import (
    DownloadJob,
    MetadataSuggestion,
    MetadataIssue,
    Playlist,
    Song,
    SyncSource,
    Task,
)
from app.domain.download import JobStatus
from app.domain.task import TaskStatus, TaskType
from app.services.dashboard import (
    get_download_trends,
    get_dashboard_snapshot,
    get_dashboard_stats,
    get_queue_health,
    serialize_dashboard_activity,
)
from app.database.session import SessionLocal
from app.web.templates import template_context, templates


def test_dashboard_download_trends_and_queue_health_are_bounded_and_aggregate_only():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 22, 12, 0)
    with Session(engine) as db:
        db.add_all([
            DownloadJob(spotify_url="complete", title="job", artist="artist", status="completed", completed_at=datetime(2026, 7, 22, 8), created_at=datetime(2026, 7, 22, 7), started_at=datetime(2026, 7, 22, 7, 5)),
            DownloadJob(spotify_url="failed", title="job", artist="artist", status="failed", completed_at=datetime(2026, 7, 20, 8)),
            DownloadJob(spotify_url="cancelled", title="job", artist="artist", status="cancelled", completed_at=datetime(2026, 7, 17, 8)),
            DownloadJob(spotify_url="old", title="job", artist="artist", status="completed", completed_at=datetime(2026, 7, 15, 8)),
            DownloadJob(spotify_url="queued", title="job", artist="artist", status="queued", created_at=datetime(2026, 7, 22, 11, 53)),
            DownloadJob(spotify_url="running", title="job", artist="artist", status="running", created_at=datetime(2026, 7, 22, 10), started_at=datetime(2026, 7, 22, 10, 10), heartbeat_at=now),
            DownloadJob(spotify_url="paused", title="job", artist="artist", status="paused"),
        ])
        db.commit()
        trends = get_download_trends(db, now=now)
        assert trends["period_days"] == 7
        assert [bucket["date"] for bucket in trends["daily"]] == ["2026-07-16", "2026-07-17", "2026-07-18", "2026-07-19", "2026-07-20", "2026-07-21", "2026-07-22"]
        assert trends["completed"] == trends["completed_today"] == 1
        assert trends["failed"] == trends["cancelled"] == 1
        assert trends["success_rate"] == round(1 / 3, 3)
        assert trends["daily"][2] == {"date": "2026-07-18", "completed": 0, "failed": 0, "cancelled": 0}
        health = get_queue_health(db, now=now, configured_workers=4)
        assert health == {"active_workers": 1, "configured_workers": 4, "utilization": 0.25, "queued_jobs": 1, "running_jobs": 1, "paused_jobs": 1, "oldest_queue_seconds": 420, "average_queue_wait_seconds": 450, "longest_running_seconds": 6600, "stalled_jobs": 0, "stale_after_seconds": 30, "stalled": False}


def test_queue_health_uses_null_durations_when_no_matching_jobs():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        health = get_queue_health(db, now=datetime(2026, 7, 22), configured_workers=0)
        assert health["utilization"] is None
        assert health["oldest_queue_seconds"] is None
        assert health["average_queue_wait_seconds"] is None
        assert health["longest_running_seconds"] is None
        assert health["stalled"] is False
        assert health["stalled_jobs"] == 0


def test_queue_health_detects_only_expired_running_heartbeats():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 22, 12)
    with Session(engine) as db:
        db.add_all(
            [
                DownloadJob(
                    spotify_url="fresh",
                    title="Fresh",
                    artist="Artist",
                    status="running",
                    started_at=datetime(2026, 7, 22, 11, 50),
                    heartbeat_at=datetime(2026, 7, 22, 11, 59, 50),
                ),
                DownloadJob(
                    spotify_url="stale",
                    title="Stale",
                    artist="Artist",
                    status="running",
                    started_at=datetime(2026, 7, 22, 11, 40),
                    heartbeat_at=datetime(2026, 7, 22, 11, 59),
                ),
                DownloadJob(
                    spotify_url="legacy",
                    title="Legacy",
                    artist="Artist",
                    status="running",
                    started_at=datetime(2026, 7, 22, 11, 30),
                ),
            ]
        )
        db.commit()
        health = get_queue_health(db, now=now, configured_workers=4)
        assert health["stalled"] is True
        assert health["stalled_jobs"] == 2
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
                MetadataIssue(
                    identity_key="dashboard-open-metadata", rule_id="missing_genre", rule_version="1",
                    entity_type="song", entity_id="1", song_id=1, severity="warning", status="open",
                    title="Missing genre", explanation="Missing genre",
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
        assert snapshot["attention"] == {
            "healthy": False,
            "headline": "Items need attention",
            "message": "5 current items across 5 categories need attention.",
            "total_count": 5,
            "critical_count": 2,
            "warning_count": 2,
            "info_count": 1,
            "items": [
                {
                    "key": "failed_downloads",
                    "severity": "critical",
                    "count": 1,
                    "title": "Failed downloads",
                    "description": "1 item requires attention",
                    "href": "/downloads?status=failed",
                    "action_label": "Review",
                    "recovery_action": None,
                    "recovery_label": None,
                },
                {
                    "key": "missing_files",
                    "severity": "critical",
                    "count": 1,
                    "title": "Missing library files",
                    "description": "1 item requires attention",
                    "href": "/library?availability=missing",
                    "action_label": "Review",
                    "recovery_action": "verify_files",
                    "recovery_label": "Verify files",
                },
                {
                    "key": "maintenance_jobs",
                    "severity": "warning",
                    "count": 1,
                    "title": "Library maintenance jobs",
                    "description": "1 item requires attention",
                    "href": "/library/health#library-jobs",
                    "action_label": "Review",
                    "recovery_action": None,
                    "recovery_label": None,
                },
                {
                    "key": "pending_metadata",
                    "severity": "warning",
                    "count": 1,
                    "title": "Open metadata issues",
                    "description": "1 item requires attention",
                    "href": "/library/health?metadata_status=open#metadata-issues-title",
                    "action_label": "Review",
                    "recovery_action": "analyze_metadata",
                    "recovery_label": "Analyze metadata",
                },
                {
                    "key": "missing_artwork",
                    "severity": "info",
                    "count": 1,
                    "title": "Missing artwork",
                    "description": "1 item requires attention",
                    "href": "/library?missing_artwork=true",
                    "action_label": "Review",
                    "recovery_action": "refresh_library",
                    "recovery_label": "Refresh library",
                },
            ],
        }
        attention = snapshot["attention"]
        assert attention["total_count"] == sum(item["count"] for item in attention["items"])
        assert attention["healthy"] == (not attention["items"] and attention["total_count"] == 0)
        for severity in ("critical", "warning", "info"):
            assert attention[f"{severity}_count"] == sum(
                item["count"] for item in attention["items"] if item["severity"] == severity
            )
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
            "newest_album": {
                "name": "Album",
                "artist": "Artist",
                "song_count": 1,
                "storage_bytes": 0,
                "year": None,
            },
            "oldest_album": {
                "name": "Album",
                "artist": "Artist",
                "song_count": 1,
                "storage_bytes": 0,
                "year": None,
            },
        }
        assert snapshot["maintenance"] == [
            {
                "id": 1,
                "name": "Refresh Library",
                "status": "completed_with_errors",
                "completed": 2,
                "failed": 1,
                "skipped": 0,
                "total": 3,
                "error_code": "INDEX_ERROR",
            }
        ]
        assert [item["id"] for item in snapshot["collections"]] == [
            "recently-added",
            "missing-artwork",
            "missing-metadata",
            "highest-bitrate",
            "large-albums",
        ]


def test_dashboard_attention_excludes_healthy_categories_and_counts_bulk_failures():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            Task(
                name="Bulk update",
                spotify_url="library://bulk/update",
                task_type=TaskType.LIBRARY_BULK.value,
                status=TaskStatus.FAILED.value,
                error_summary="A private filesystem path must never be exposed",
                operation_payload='{"private": "payload"}',
            )
        )
        db.commit()

        attention = get_dashboard_snapshot(db)["attention"]

        assert attention == {
            "healthy": False,
            "headline": "Items need attention",
            "message": "1 current items across 1 categories need attention.",
            "total_count": 1,
            "critical_count": 0,
            "warning_count": 1,
            "info_count": 0,
            "items": [
                {
                    "key": "bulk_jobs",
                    "severity": "warning",
                    "count": 1,
                    "title": "Library bulk jobs",
                    "description": "1 item requires attention",
                    "href": "/library/health#library-jobs",
                    "action_label": "Review",
                    "recovery_action": None,
                    "recovery_label": None,
                }
            ],
        }
        assert "private" not in str(attention)
        assert "path" not in str(attention)


def test_dashboard_failed_attention_matches_downloads_failed_filter():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            DownloadJob(
                spotify_url="spotify:track:cancelled",
                title="Cancelled",
                artist="Artist",
                status=JobStatus.CANCELLED.value,
            )
        )
        db.commit()

        snapshot = get_dashboard_snapshot(db)

        assert snapshot["kpis"]["failed_jobs"] == 0
        assert snapshot["downloads"]["failed"] == 0
        assert snapshot["attention"]["healthy"] is True
        assert snapshot["attention"]["items"] == []


def test_dashboard_attention_contract_is_healthy_only_when_normalized_items_are_empty():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        healthy = get_dashboard_snapshot(db)["attention"]
        assert healthy["healthy"] is True
        assert healthy["total_count"] == 0
        assert healthy["items"] == []
        db.add(DownloadJob(spotify_url="spotify:track:failed", title="Failed", artist="Artist", status="failed"))
        db.commit()
        attention = get_dashboard_snapshot(db)["attention"]
        assert attention["healthy"] is False
        assert attention["total_count"] == sum(item["count"] for item in attention["items"])
        assert attention["headline"] == "Items need attention"


def test_initial_dashboard_html_uses_the_same_attention_snapshot_as_the_api():
    with SessionLocal() as db:
        db.add(DownloadJob(spotify_url="spotify:track:failed", title="Failed", artist="Artist", status="failed"))
        db.commit()
    with SessionLocal() as db:
        snapshot = get_dashboard_snapshot(db)["attention"]
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = templates.TemplateResponse(
        "dashboard.html", template_context(request=request, stats={}, dashboard_snapshot={"attention": snapshot}, page="dashboard")
    )
    html = response.body.decode()
    assert snapshot["healthy"] is False
    assert f'>{snapshot["total_count"]} issue<' in html
    assert 'data-attention-key="failed_downloads"' in html
    assert "Everything looks healthy" not in html


def test_dashboard_activity_serialization_is_timestamped_and_privacy_safe():
    timestamp = datetime.now(UTC).replace(tzinfo=None)
    job = DownloadJob(
        id=42,
        spotify_url="spotify:track:timeline",
        title="Timeline song",
        artist="Timeline artist",
        status=JobStatus.FAILED.value,
        completed_at=timestamp,
        error="Do not expose internal diagnostic details",
        output_file="/private/music/timeline.mp3",
    )

    activity = serialize_dashboard_activity(job)

    assert activity == {
        "id": 42,
        "status": "failed",
        "title": "Timeline song",
        "artist": "Timeline artist",
        "event_at": timestamp.isoformat(),
    }
    assert "private" not in str(activity)
    assert "diagnostic" not in str(activity)
