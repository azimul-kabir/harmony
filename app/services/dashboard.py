from datetime import UTC, datetime

from sqlalchemy import case, func, select

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
from app.services.collections import collection_engine
from app.services.library_analytics import library_analytics
from app.services.library_predicates import missing_metadata_expression


def get_dashboard_stats(db):
    # The Library views deliberately omit rows retained for files that have
    # disappeared from disk.  Keep the dashboard's Songs card on that same
    # definition so both surfaces report the usable library size.
    songs = (
        db.scalar(
            select(func.count(Song.id)).where(Song.availability_status == "available")
        )
        or 0
    )

    downloads = db.scalar(select(func.count(DownloadJob.id))) or 0

    sources = db.scalar(select(func.count(SyncSource.id))) or 0

    failed = (
        db.scalar(
            select(func.count(DownloadJob.id)).where(
                DownloadJob.status.in_(
                    (JobStatus.FAILED.value, JobStatus.CANCELLED.value)
                )
            )
        )
        or 0
    )

    return {
        "songs": songs,
        "downloads": downloads,
        "sources": sources,
        "failed": failed,
    }


def serialize_dashboard_activity(job: DownloadJob) -> dict:
    """Return a bounded, display-safe download event for the Dashboard timeline."""
    event_at = job.completed_at or job.started_at or job.created_at
    return {
        "id": job.id,
        "status": job.status,
        "title": job.title,
        "artist": job.artist,
        "event_at": event_at.isoformat() if event_at else None,
    }


def get_dashboard_snapshot(db) -> dict:
    """Return the compact, actionable dashboard read model."""
    stats = get_dashboard_stats(db)
    analytics = library_analytics.calculate(db)
    available = Song.availability_status == "available"
    missing_metadata = missing_metadata_expression()
    health_row = db.execute(
        select(
            func.coalesce(
                func.sum(case((Song.artwork_status == "missing", 1), else_=0)), 0
            ),
            func.coalesce(func.sum(case((missing_metadata, 1), else_=0)), 0),
        ).where(available)
    ).one()
    missing_files = (
        db.scalar(
            select(func.count(Song.id)).where(Song.availability_status == "missing")
        )
        or 0
    )
    total_songs = int(analytics["songs"] or 0)
    health_score = max(
        0,
        min(
            100,
            round(
                100
                * (
                    1
                    - (
                        (
                            int(health_row[0]) * 0.30
                            + int(health_row[1]) * 0.50
                            + missing_files * 0.20
                        )
                        / max(total_songs + missing_files, 1)
                    )
                )
            ),
        ),
    )

    today = datetime.now(UTC).replace(
        tzinfo=None, hour=0, minute=0, second=0, microsecond=0
    )
    downloads = db.execute(
        select(
            func.coalesce(
                func.sum(
                    case((DownloadJob.status == JobStatus.RUNNING.value, 1), else_=0)
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case((DownloadJob.status == JobStatus.QUEUED.value, 1), else_=0)
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            DownloadJob.status.in_(
                                (JobStatus.FAILED.value, JobStatus.CANCELLED.value)
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(case((DownloadJob.completed_at >= today, 1), else_=0)), 0
            ),
        )
    ).one()
    suggestions_pending = (
        db.scalar(
            select(func.count(MetadataSuggestion.id)).where(
                MetadataSuggestion.status == "pending"
            )
        )
        or 0
    )
    attention = _get_attention_summary(
        failed_downloads=stats["failed"],
        missing_files=int(missing_files),
        missing_artwork=int(health_row[0]),
        pending_suggestions=int(suggestions_pending),
        task_counts=_attention_task_counts(db),
    )
    playlist_count = db.scalar(select(func.count(Playlist.id))) or 0
    collection_ids = (
        "recently-added",
        "missing-artwork",
        "missing-metadata",
        "highest-bitrate",
        "large-albums",
    )
    collections = [
        definition.to_dict(song_count=collection_engine.count(db, definition.id))
        for collection_id in collection_ids
        if (definition := collection_engine.get(collection_id)) is not None
    ]
    maintenance = db.scalars(
        select(Task)
        .where(
            Task.task_type.in_(
                (TaskType.LIBRARY_BULK.value, TaskType.LIBRARY_MAINTENANCE.value)
            ),
            Task.status.in_(
                (
                    TaskStatus.CANCELLED.value,
                    TaskStatus.COMPLETED.value,
                    TaskStatus.COMPLETED_WITH_ERRORS.value,
                    TaskStatus.FAILED.value,
                    TaskStatus.INTERRUPTED.value,
                )
            ),
        )
        .order_by(Task.completed_at.desc(), Task.id.desc())
        .limit(3)
    ).all()

    return {
        "stats": stats,
        "kpis": {
            "songs": total_songs,
            "albums": int(analytics["albums"] or 0),
            "artists": int(analytics["artists"] or 0),
            "sources": stats["sources"],
            "playlists": playlist_count,
            "storage_bytes": int(analytics["storage_bytes"] or 0),
            "health_score": health_score,
            "failed_jobs": stats["failed"],
        },
        "downloads": {
            "running": int(downloads[0]),
            "queued": int(downloads[1]),
            "failed": int(downloads[2]),
            "completed_today": int(downloads[3]),
        },
        "health": {
            "score": health_score,
            "missing_artwork": int(health_row[0]),
            "missing_metadata": int(health_row[1]),
            "missing_files": int(missing_files),
            "pending_suggestions": int(suggestions_pending),
        },
        "attention": attention,
        # Keep richer dashboard insights owned by LibraryAnalyticsService.  The
        # dashboard must not introduce its own filesystem access or grouping
        # queries for facts that other Library consumers need.
        "analytics": {
            "genres": int(analytics["genres"] or 0),
            "average_bitrate": int(analytics["average_bitrate"] or 0),
            "average_duration": float(analytics["average_duration"] or 0),
            "recently_added": int(analytics["recently_added"] or 0),
            "largest_album": analytics["largest_album"],
            "newest_album": analytics["newest_album"],
            "oldest_album": analytics["oldest_album"],
        },
        "maintenance": [
            {
                "id": task.id,
                "name": task.name,
                "status": task.status,
                "completed": task.completed_items,
                "failed": task.failed_items,
                "skipped": task.skipped_items,
                "total": task.total_items,
                "error_code": task.error_code,
            }
            for task in maintenance
        ],
        "collections": collections,
    }


_ATTENTION_DEFINITIONS = (
    # Order is operational priority within a severity; do not sort by count.
    (
        "failed_downloads",
        "critical",
        "Failed downloads",
        "/downloads?status=failed",
        "Review",
        None,
        None,
    ),
    (
        "missing_files",
        "critical",
        "Missing library files",
        "/library/health",
        "Review",
        "verify_files",
        "Verify files",
    ),
    (
        "maintenance_jobs",
        "warning",
        "Library maintenance jobs",
        "/library/health",
        "Review",
        None,
        None,
    ),
    (
        "bulk_jobs",
        "warning",
        "Library bulk jobs",
        "/library/health",
        "Review",
        None,
        None,
    ),
    (
        "pending_metadata",
        "warning",
        "Pending metadata suggestions",
        "/library/health",
        "Review",
        "analyze_metadata",
        "Analyze metadata",
    ),
    (
        "missing_artwork",
        "info",
        "Missing artwork",
        "/library?missing_artwork=true",
        "Review",
        "refresh_library",
        "Refresh library",
    ),
)


def _attention_task_counts(db) -> dict[str, int]:
    """Count only terminal task outcomes that require a recovery review."""
    needs_review = (
        TaskStatus.FAILED.value,
        TaskStatus.COMPLETED_WITH_ERRORS.value,
        TaskStatus.INTERRUPTED.value,
    )
    row = db.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (Task.task_type == TaskType.LIBRARY_MAINTENANCE.value, 1),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case((Task.task_type == TaskType.LIBRARY_BULK.value, 1), else_=0)
                ),
                0,
            ),
        ).where(
            Task.task_type.in_(
                (TaskType.LIBRARY_MAINTENANCE.value, TaskType.LIBRARY_BULK.value)
            ),
            Task.status.in_(needs_review),
        )
    ).one()
    return {"maintenance_jobs": int(row[0]), "bulk_jobs": int(row[1])}


def _get_attention_summary(
    *,
    failed_downloads: int,
    missing_files: int,
    missing_artwork: int,
    pending_suggestions: int,
    task_counts: dict[str, int],
) -> dict:
    """Create a privacy-safe, navigation-only Dashboard attention contract."""
    counts = {
        "failed_downloads": failed_downloads,
        "missing_files": missing_files,
        "maintenance_jobs": task_counts["maintenance_jobs"],
        "bulk_jobs": task_counts["bulk_jobs"],
        "pending_metadata": pending_suggestions,
        "missing_artwork": missing_artwork,
    }
    items = []
    for (
        key,
        severity,
        title,
        href,
        action_label,
        recovery_action,
        recovery_label,
    ) in _ATTENTION_DEFINITIONS:
        count = int(counts[key])
        if count:
            noun = "item" if count == 1 else "items"
            verb = "requires" if count == 1 else "require"
            items.append(
                {
                    "key": key,
                    "severity": severity,
                    "count": count,
                    "title": title,
                    "description": f"{count} {noun} {verb} attention",
                    "href": href,
                    "action_label": action_label,
                    "recovery_action": recovery_action,
                    "recovery_label": recovery_label,
                }
            )
    severity_counts = {
        severity: sum(item["count"] for item in items if item["severity"] == severity)
        for severity in ("critical", "warning", "info")
    }
    return {
        "total_count": sum(item["count"] for item in items),
        "critical_count": severity_counts["critical"],
        "warning_count": severity_counts["warning"],
        "info_count": severity_counts["info"],
        "items": items,
    }
