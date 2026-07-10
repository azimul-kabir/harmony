from pathlib import Path

from app.core.config import get_settings

settings = get_settings()


INVALID_CHARS = '<>:"/\\|?*'


def _safe(value: str) -> str:
    value = value.strip()

    for ch in INVALID_CHARS:
        value = value.replace(ch, "_")

    return value


def build_destination(metadata: dict) -> Path:
    source = Path(metadata["path"])

    album_artist = _safe(
        metadata.get("album_artist") or metadata.get("artist") or "Unknown Artist"
    )

    album = metadata.get("album")
    title = _safe(metadata.get("title") or source.stem)

    track = metadata.get("track")

    extension = source.suffix.lower()

    if album:
        album = _safe(album)

        if track is not None:
            filename = f"{track:02d} - {title}{extension}"
        else:
            filename = f"{title}{extension}"

        return Path(settings.music_path) / album_artist / album / filename

    return Path(settings.music_path) / album_artist / "Singles" / f"{title}{extension}"
