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

    artists = db.scalar(
        select(func.count(func.distinct(Song.artist)))
    ) or 0

    albums = db.scalar(
        select(func.count(func.distinct(Song.album)))
    ) or 0

    import shutil
    from app.core.config import get_settings
    settings = get_settings()

    try:
        total, used, free = shutil.disk_usage(settings.music_path)
        storage_used_gb = round(used / (1024**3), 2)
        storage_free_gb = round(free / (1024**3), 2)
        storage_total_gb = round(total / (1024**3), 2)
    except Exception:
        storage_used_gb = 0
        storage_free_gb = 0
        storage_total_gb = 0

    return {
        "songs": songs,
        "artists": artists,
        "albums": albums,
        "downloads": downloads,
        "sources": sources,
        "failed": failed,
        "storage": {
            "used_gb": storage_used_gb,
            "free_gb": storage_free_gb,
            "total_gb": storage_total_gb
        }
    }