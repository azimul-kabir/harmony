"""Explicit, guarded writes of canonical Song metadata to audio files.

This module is deliberately not used by discovery or canonical metadata
application.  Calling it is the user-visible, final "write tags" stage.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from mutagen import File
from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK, TXXX
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3

from app.core.config import get_settings
from app.database.models import MetadataHistory, Song
from app.services.library_scanner import index_file
from app.services.artwork import ArtworkService

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_MB = {
    "musicbrainz_artist_id": "MusicBrainz Artist Id",
    "musicbrainz_release_artist_id": "MusicBrainz Album Artist Id",
    "musicbrainz_release_id": "MusicBrainz Album Id",
    "musicbrainz_release_group_id": "MusicBrainz Release Group Id",
    "musicbrainz_recording_id": "MusicBrainz Track Id",
}
_FIELDS = ("title", "artist", "album_artist", "album", "track", "disc", "release_date", *_MB)


class TagWriteError(Exception):
    pass


def _safe_path(song: Song) -> Path:
    root = Path(get_settings().music_path).resolve()
    raw = Path(song.path)
    # Never follow a symlink selected by an indexed path; this makes an escape
    # impossible even where a symlink's resolved target is below the root.
    if raw.is_symlink():
        raise TagWriteError("The audio file is not safe to modify.")
    try:
        target = raw.resolve(strict=True)
        target.relative_to(root)
    except (OSError, ValueError, RuntimeError, FileNotFoundError):
        raise TagWriteError("The audio file is outside Harmony's music library or unavailable.")
    if not target.is_file():
        raise TagWriteError("The audio file is unavailable.")
    return target


def _number(number: int | None, total: int | None) -> str | None:
    return None if number is None else f"{number}/{total}" if total else str(number)


def _canonical(song: Song) -> dict[str, Any]:
    return {"title": song.title, "artist": song.artist, "album_artist": song.album_artist,
            "album": song.album, "track": _number(song.track, song.track_total),
            "disc": _number(song.disc, song.disc_total),
            "release_date": song.release_date or (str(song.year) if song.year else None),
            **{key: getattr(song, key) for key in _MB}}


def _id3_values(path: Path) -> dict[str, Any]:
    tags = ID3(path)
    frame = lambda key: str(tags.get(key).text[0]) if tags.get(key) and getattr(tags.get(key), "text", None) else None
    out = {"title": frame("TIT2"), "artist": frame("TPE1"), "album_artist": frame("TPE2"),
           "album": frame("TALB"), "track": frame("TRCK"), "disc": frame("TPOS"), "release_date": frame("TDRC")}
    txxx = {str(x.desc): str(x.text[0]) for x in tags.getall("TXXX") if x.text}
    out.update({key: txxx.get(desc) for key, desc in _MB.items()})
    return out


def _embedded_artwork(path: Path) -> bytes | None:
    if path.suffix.lower() == ".mp3":
        covers = [item for item in ID3(path).getall("APIC") if item.type == 3]
        return bytes(covers[0].data) if covers else None
    if path.suffix.lower() == ".flac":
        covers = [item for item in FLAC(path).pictures if item.type == 3]
        return bytes(covers[0].data) if covers else None
    return None


def _artwork_preview(song: Song, path: Path | None) -> dict[str, Any]:
    if song.artwork is None:
        return {"status": "no canonical artwork", "canonical_available": False, "will_change": False}
    cached = ArtworkService().validated_cached_bytes(song.artwork)
    if cached is None:
        return {"status": "cached artwork missing or unreadable", "canonical_available": False, "will_change": False}
    if path is None or path.suffix.lower() not in {".mp3", ".flac"}:
        return {"status": "artwork unsupported for this format", "canonical_available": True, "will_change": False}
    current = _embedded_artwork(path)
    if current == cached[0]:
        status = "embedded artwork already matches"
    else:
        status = "embedded artwork will be added" if current is None else "embedded artwork will be replaced"
    return {"status": status, "canonical_available": True, "will_change": current != cached[0]}


def preview(song: Song) -> dict[str, Any]:
    try:
        path = _safe_path(song)
        if path.suffix.lower() != ".mp3":
            audio = File(path, easy=True)
            if audio is None:
                return {"available": False, "reason": "unsupported", "fields": [], "artwork": _artwork_preview(song, None)}
            current = {"title": (audio.tags or {}).get("title", [None])[0], "artist": (audio.tags or {}).get("artist", [None])[0], "album_artist": (audio.tags or {}).get("albumartist", [None])[0], "album": (audio.tags or {}).get("album", [None])[0], "track": (audio.tags or {}).get("tracknumber", [None])[0], "disc": (audio.tags or {}).get("discnumber", [None])[0], "release_date": (audio.tags or {}).get("date", [None])[0]}
            current.update({key: None for key in _MB})
        else:
            current = _id3_values(path)
    except TagWriteError:
        return {"available": False, "reason": "missing_or_unsafe", "fields": [], "artwork": _artwork_preview(song, None)}
    except Exception:
        return {"available": False, "reason": "unsupported", "fields": [], "artwork": _artwork_preview(song, None)}
    desired = _canonical(song)
    return {"available": any(value not in (None, "") for value in desired.values()), "reason": None,
            "fields": [{"field": key, "current": current.get(key), "canonical": desired[key], "will_change": str(current.get(key) or "") != str(desired[key] or "")} for key in _FIELDS],
            "artwork": _artwork_preview(song, path)}


def _write_mp3(path: Path, values: dict[str, Any]) -> None:
    audio = MP3(path)
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags
    frames = {"title": ("TIT2", TIT2), "artist": ("TPE1", TPE1), "album_artist": ("TPE2", TPE2), "album": ("TALB", TALB), "track": ("TRCK", TRCK), "disc": ("TPOS", TPOS), "release_date": ("TDRC", TDRC)}
    for key, (name, cls) in frames.items():
        if values[key] not in (None, ""):
            tags.setall(name, [cls(encoding=3, text=str(values[key]))])
    for key, desc in _MB.items():
        tags.delall("TXXX:" + desc)
        if values[key] not in (None, ""):
            tags.add(TXXX(encoding=3, desc=desc, text=str(values[key])))
    audio.save()


def _write_generic(path: Path, values: dict[str, Any]) -> None:
    audio = File(path, easy=True)
    if audio is None:
        raise TagWriteError("This audio format is not supported for tag writing.")
    if audio.tags is None:
        audio.add_tags()
    mapping = {"title": "title", "artist": "artist", "album_artist": "albumartist", "album": "album", "track": "tracknumber", "disc": "discnumber", "release_date": "date"}
    for key, tag in mapping.items():
        if values[key] not in (None, ""):
            audio.tags[tag] = [str(values[key])]
    # Vorbis comments accept these names; unsupported containers simply retain
    # their standard fields rather than risking a destructive conversion.
    if path.suffix.lower() in {".flac", ".ogg", ".opus"}:
        for key, desc in _MB.items():
            if values[key] not in (None, ""):
                audio.tags[desc] = [str(values[key])]
    audio.save()


def _write_artwork(path: Path, data: bytes, mime: str) -> None:
    if path.suffix.lower() == ".mp3":
        audio = MP3(path)
        if audio.tags is None: audio.add_tags()
        # Delete only front covers, retaining artist/booklet/other APIC frames.
        audio.tags.setall("APIC", [item for item in audio.tags.getall("APIC") if item.type != 3])
        audio.tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
        audio.save()
    else:
        raise TagWriteError("Artwork embedding is not supported for this audio format.")


def _write_flac_artwork(path: Path, data: bytes, mime: str) -> None:
    audio = FLAC(path)
    others = [item for item in audio.pictures if item.type != 3]
    audio.clear_pictures()
    for picture in others: audio.add_picture(picture)
    picture = Picture(); picture.type = 3; picture.mime = mime; picture.desc = "Cover"; picture.data = data
    audio.add_picture(picture); audio.save()


def write_song(db, song: Song, *, embed_artwork: bool = True) -> dict[str, Any]:
    check = preview(song)
    if not check["available"]:
        return {"status": "skipped", "reason": check["reason"]}
    path = _safe_path(song)
    with _locks_guard:
        lock = _locks.setdefault(str(path), threading.Lock())
    if not lock.acquire(blocking=False):
        return {"status": "skipped", "reason": "already_writing"}
    backup_name = None
    try:
        before = path.stat()
        fd, backup_name = tempfile.mkstemp(prefix=".harmony-tags-", dir=path.parent)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as out, path.open("rb") as source:
            shutil.copyfileobj(source, out)
        values = _canonical(song)
        if path.suffix.lower() == ".mp3": _write_mp3(path, values)
        elif path.suffix.lower() in {".flac", ".m4a", ".ogg", ".opus"}: _write_generic(path, values)
        else: return {"status": "unsupported"}
        artwork_result = "unchanged"
        if embed_artwork and check["artwork"]["will_change"]:
            cached = ArtworkService().validated_cached_bytes(song.artwork)
            if cached is None:
                artwork_result = "unavailable"
            elif path.suffix.lower() == ".flac":
                _write_flac_artwork(path, *cached); artwork_result = "embedded"
            elif path.suffix.lower() == ".mp3":
                _write_artwork(path, *cached); artwork_result = "embedded"
        elif embed_artwork and check["artwork"]["status"] == "cached artwork missing or unreadable":
            artwork_result = "unavailable"
        elif embed_artwork and check["artwork"]["status"] == "artwork unsupported for this format":
            artwork_result = "unsupported"
        # Ensure a scanner using second-granularity timestamps sees this write.
        os.utime(path, ns=(before.st_atime_ns, max(before.st_mtime_ns + 1_000_000_000, path.stat().st_mtime_ns)))
        reread = preview(song)
        changed = [item["field"] for item in reread["fields"] if item["canonical"] not in (None, "") and item["will_change"]]
        if changed:
            raise TagWriteError("Tag verification failed.")
        if artwork_result == "embedded" and reread["artwork"]["status"] != "embedded artwork already matches":
            raise TagWriteError("Artwork verification failed.")
        index_file(db, path, force=True, commit=False)
        for field in [item["field"] for item in check["fields"] if item["will_change"]]:
            db.add(MetadataHistory(entity_type="song", entity_id=song.id, field_name=field, previous_value=None, new_value=None, provider="file_tag_write", change_source="file_tag_write", audio_file_modified=True, reversible=False))
        if artwork_result == "embedded":
            db.add(MetadataHistory(entity_type="song", entity_id=song.id, field_name="artwork", previous_value=None, new_value="embedded", provider="file_tag_write", change_source="file_tag_write", audio_file_modified=True, reversible=False))
        db.commit()
        return {"status": "succeeded", "changed_fields": [x["field"] for x in check["fields"] if x["will_change"]], "artwork": artwork_result}
    except Exception as exc:
        db.rollback()
        if backup_name:
            try: os.replace(backup_name, path)
            except OSError: pass
        return {"status": "failed", "reason": str(exc) if isinstance(exc, TagWriteError) else "Unable to write audio tags."}
    finally:
        if backup_name:
            try: os.unlink(backup_name)
            except OSError: pass
        lock.release()
