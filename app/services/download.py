import time
from pathlib import Path

from app.core.config import get_settings
from app.downloaders.spotdl import SpotDLClient
from app.providers.download_sources import get_source
from app.domain.track import Track
from app.core.logging import logger
from app.domain.download_outcome import DownloadCancelled
from app.services.direct_acquisition import DirectYouTubeAcquirer

settings = get_settings()
client = SpotDLClient()
direct_client = DirectYouTubeAcquirer()


def download_track(track: Track, job_id: int | None = None) -> Path:
    if track.source_provider == "youtube_music":
        return get_source("youtube_music").download(track, settings.staging_path, job_id)
    started = time.monotonic()
    try:
        return direct_client.download(track, Path(settings.staging_path), job_id)
    except DownloadCancelled:
        raise
    except Exception as direct_error:
        logger.bind(job_id=job_id, spotdl_fallback=True).warning(
            "Entering SpotDL acquisition fallback job={} direct_reason={} spotdl_fallback=true",
            job_id, getattr(direct_error, "reason_code", type(direct_error).__name__),
        )
        fallback_started = time.monotonic()
        try:
            return client.download(track, Path(settings.staging_path), job_id)
        finally:
            logger.bind(
                job_id=job_id,
                spotdl_fallback=True,
                spotdl_fallback_seconds=round(time.monotonic() - fallback_started, 3),
                total_acquisition_seconds=round(time.monotonic() - started, 3),
            ).info(
                "Acquisition fallback completed job={} spotdl_fallback=true "
                "spotdl_fallback_seconds={} total_acquisition_seconds={}",
                job_id, round(time.monotonic() - fallback_started, 3),
                round(time.monotonic() - started, 3),
            )
