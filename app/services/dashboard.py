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
                DownloadJob.status == JobStatus.FAILED.value
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


def get_dashboard_snapshot(db) -> dict:
    """Return the compact, actionable dashboard read model."""
    stats = get_dashboard_stats(db)
    analytics = library_analytics.calculate(db)
    available = Song.availability_status == "available"
    missing_metadata = missing_metadata_expression()
    health = db.execute(
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
                            int(health[0]) * 0.30
                            + int(health[1]) * 0.50
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
                    case((DownloadJob.status == JobStatus.FAILED.value, 1), else_=0)
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
            "missing_artwork": int(health[0]),
            "missing_metadata": int(health[1]),
            "missing_files": int(missing_files),
            "pending_suggestions": int(suggestions_pending),
        },
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
