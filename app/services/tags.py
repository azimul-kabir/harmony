from pathlib import Path

from mutagen import File

from app.domain.track import Track


SUPPORTED_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".m4a",
    ".ogg",
    ".opus",
}


def _first(tags, *keys):
    if not tags:
        return None

    for key in keys:
        value = tags.get(key)
        if value:
            if isinstance(value, list):
                return str(value[0])
            if hasattr(value, "text"):
                return str(value.text[0])
            return str(value)

    return None


def _int(value):
    if not value:
        return None
    try:
        return int(str(value).split("/")[0])
    except Exception:
        return None


def read_tags(path: Path) -> Track:
    audio = File(path, easy=False)
    easy = File(path, easy=True)

    tags = audio.tags if audio else {}
    easy_tags = easy.tags if easy else {}

    return Track(
        title=_first(easy_tags, "title"),
        artist=_first(easy_tags, "artist"),
        album_artist=_first(easy_tags, "albumartist"),
        album=_first(easy_tags, "album"),
        track=_int(_first(easy_tags, "tracknumber")),
        disc=_int(_first(easy_tags, "discnumber")),
        year=_int(_first(easy_tags, "date")),
        genre=_first(easy_tags, "genre"),
        duration=audio.info.length if audio else None,
        spotify_track_id=_first(tags, "spotify_track_id"),
        spotify_album_id=_first(tags, "spotify_album_id"),
        isrc=_first(tags, "isrc"),
    )