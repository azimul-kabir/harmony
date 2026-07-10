from pathlib import Path

from app.core.config import get_settings

settings = get_settings()


def build_destination(metadata: dict) -> Path:
    album_artist = (
        metadata.get("album_artist")
        or metadata.get("artist")
        or "Unknown Artist"
    )

    album = metadata.get("album")
    title = metadata.get("title") or Path(metadata["path"]).stem
    track = metadata.get("track")

    extension = Path(metadata["path"]).suffix

    if album:
        filename = (
            f"{track:02d} - {title}{extension}"
            if track
            else f"{title}{extension}"
        )

        return (
            Path(settings.music_path)
            / album_artist
            / album
            / filename
        )

    return (
        Path(settings.music_path)
        / album_artist
        / "Singles"
        / f"{title}{extension}"
    )