from pathlib import Path

from app.core.config import get_settings
from app.downloaders.spotdl import SpotDLClient
from app.domain.track import Track

settings = get_settings()
client = SpotDLClient()


def download_track(track: Track) -> Path:
    return client.download(
        track,
        Path(settings.staging_path),
    )