from sqlalchemy import func, select

from app.database.models import (
    DownloadJob,
    Song,
    SyncSource,
)
from app.domain.download import JobStatus


def get_dashboard_stats(db):
    songs = db.scalar(
        select(func.count(Song.id))
    ) or 0

    downloads = db.scalar(
        select(func.count(DownloadJob.id))
    ) or 0

    sources = db.scalar(
        select(func.count(SyncSource.id))
    ) or 0

    failed = db.scalar(
        select(func.count(DownloadJob.id)).where(
            DownloadJob.status == JobStatus.FAILED.value
        )
    ) or 0

    return {
        "songs": songs,
        "downloads": downloads,
        "sources": sources,
        "failed": failed,
    }