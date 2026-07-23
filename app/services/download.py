from pathlib import Path

from app.core.config import get_settings
from app.downloaders.spotdl import SpotDLClient
from app.providers.download_sources import get_source
from app.domain.track import Track

settings = get_settings()
client = SpotDLClient()


def download_track(track: Track, job_id: int | None = None) -> Path:
    if track.source_provider == "youtube_music":
        return get_source("youtube_music").download(track, settings.staging_path, job_id)
    return client.download(
        track,
        Path(settings.staging_path),
    )
