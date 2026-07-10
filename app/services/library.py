from pathlib import Path
import shutil

from app.core.config import get_settings
from app.domain.track import Track

settings = get_settings()


def _safe(name: str | None) -> str:
    if not name:
        return "Unknown"

    invalid = '<>:"/\\|?*'

    for c in invalid:
        name = name.replace(c, "_")

    return name.strip()


def destination(track: Track, extension: str) -> Path:
    album_artist = _safe(track.album_artist or track.artist)
    album = _safe(track.album or "Singles")

    title = track.title or "Unknown Title"

    if track.track is not None:
        filename = f"{track.track:02d} - {_safe(title)}{extension}"
    else:
        filename = f"{_safe(title)}{extension}"

    return (
        Path(settings.music_path)
        / album_artist
        / album
        / filename
    )


def import_track(
    source: Path,
    track: Track,
) -> Path:
    dest = destination(track, source.suffix.lower())

    dest.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.move(
        str(source),
        str(dest),
    )

    return dest