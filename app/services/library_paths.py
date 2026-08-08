from pathlib import Path

from app.core.config import get_settings

settings = get_settings()


INVALID_CHARS = '<>:"/\\|?*'


def sanitize_path_component(value: str) -> str:
    """Return Harmony's canonical filesystem-safe metadata component.

    The replacement set deliberately contains only characters that cannot be
    used portably in a single path component. Unicode content is preserved.
    """
    value = value.strip()
    value = value.translate(str.maketrans({char: "_" for char in INVALID_CHARS}))
    return "_" if value in {".", ".."} else value


def build_destination(metadata: dict) -> Path:
    source = Path(metadata["path"])

    album_artist = sanitize_path_component(
        metadata.get("album_artist") or metadata.get("artist") or "Unknown Artist"
    )

    album = metadata.get("album")
    title = sanitize_path_component(metadata.get("title") or source.stem)

    track = metadata.get("track")

    extension = source.suffix.lower()

    if album:
        album = sanitize_path_component(album)

        if track is not None:
            filename = f"{track:02d} - {title}{extension}"
        else:
            filename = f"{title}{extension}"

        return Path(settings.music_path) / album_artist / album / filename

    return Path(settings.music_path) / album_artist / "Singles" / f"{title}{extension}"
