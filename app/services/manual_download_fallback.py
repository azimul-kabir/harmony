"""Explicit user-approved YouTube link acquisition for failed downloads."""

from app.database.models import DownloadJob
from app.domain.download import JobStatus
from app.domain.task import TaskType
from app.providers.download_sources import get_source
from app.services.task_service import create_task


def manual_fallback_eligible(job: DownloadJob) -> bool:
    """Any failed download may be retried from a user-supplied YouTube link.

    Failures end with many different reason codes (matching, provider
    timeouts, the SpotDL rescue, legacy rows with no code at all), and a
    specific link the user chose can help with all of them. The worker still
    validates the linked track's title and duration before importing it.
    """
    return (job.status or "").strip().lower() == JobStatus.FAILED.value


def queue_manual_fallback(db, *, job_id: int, url: str) -> DownloadJob:
    original = db.get(DownloadJob, job_id)
    if original is None:
        raise LookupError("Download not found.")
    if not manual_fallback_eligible(original):
        raise ValueError("A YouTube link can be supplied only for failed downloads.")

    source = get_source("youtube_music")
    detected = source.detect_url(url.strip())
    if detected is None or detected[0] != "track":
        raise ValueError("Choose a specific YouTube or YouTube Music track URL.")
    canonical_url = source_url = url.strip()
    source_item_id = detected[1]
    if hasattr(source, "canonical_url"):
        canonical_url = source.canonical_url("track", source_item_id)

    task = create_task(
        db=db,
        name=f"Fallback: {original.title}",
        spotify_url=f"manual-fallback://download/{original.id}",
        task_type=TaskType.TRACK_DOWNLOAD,
        total_items=1,
    )
    fallback = DownloadJob(
        task_id=task.id,
        spotify_url=original.spotify_url,
        source_provider=original.source_provider or "spotify",
        source_item_id=original.source_item_id,
        source_url=original.source_url,
        spotify_track_id=original.spotify_track_id,
        spotify_album_id=original.spotify_album_id,
        title=original.title,
        artist=original.artist,
        album=original.album,
        album_artist=original.album_artist,
        track=original.track,
        queue_position=original.queue_position,
        disc=original.disc,
        year=original.year,
        isrc=original.isrc,
        genre=original.genre,
        duration=original.duration,
        spotify_artist_ids=original.spotify_artist_ids,
        genre_provenance=original.genre_provenance,
        cover_url=original.cover_url,
        status=JobStatus.QUEUED.value,
        manual_fallback_url=canonical_url or source_url,
    )
    db.add(fallback)
    db.commit()
    db.refresh(fallback)
    return fallback
