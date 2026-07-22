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
from mutagen.id3 import ID3, TALB, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK, TXXX
from mutagen.mp3 import MP3

from app.core.config import get_settings
from app.database.models import MetadataHistory, Song
from app.services.library_scanner import index_file

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


def preview(song: Song) -> dict[str, Any]:
    try:
        path = _safe_path(song)
        if path.suffix.lower() != ".mp3":
            audio = File(path, easy=True)
            if audio is None:
                return {"available": False, "reason": "unsupported", "fields": []}
            current = {"title": (audio.tags or {}).get("title", [None])[0], "artist": (audio.tags or {}).get("artist", [None])[0], "album_artist": (audio.tags or {}).get("albumartist", [None])[0], "album": (audio.tags or {}).get("album", [None])[0], "track": (audio.tags or {}).get("tracknumber", [None])[0], "disc": (audio.tags or {}).get("discnumber", [None])[0], "release_date": (audio.tags or {}).get("date", [None])[0]}
            current.update({key: None for key in _MB})
        else:
            current = _id3_values(path)
    except TagWriteError:
        return {"available": False, "reason": "missing_or_unsafe", "fields": []}
    except Exception:
        return {"available": False, "reason": "unsupported", "fields": []}
    desired = _canonical(song)
    return {"available": any(value not in (None, "") for value in desired.values()), "reason": None,
            "fields": [{"field": key, "current": current.get(key), "canonical": desired[key], "will_change": str(current.get(key) or "") != str(desired[key] or "")} for key in _FIELDS],
            "artwork": {"current": song.artwork_status == "embedded", "canonical_available": bool(song.artwork_id), "will_change": False}}


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


def write_song(db, song: Song) -> dict[str, Any]:
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
        # Ensure a scanner using second-granularity timestamps sees this write.
        os.utime(path, ns=(before.st_atime_ns, max(before.st_mtime_ns + 1_000_000_000, path.stat().st_mtime_ns)))
        reread = preview(song)
        changed = [item["field"] for item in reread["fields"] if item["canonical"] not in (None, "") and item["will_change"]]
        if changed:
            raise TagWriteError("Tag verification failed.")
        index_file(db, path, force=True, commit=False)
        for field in [item["field"] for item in check["fields"] if item["will_change"]]:
            db.add(MetadataHistory(entity_type="song", entity_id=song.id, field_name=field, previous_value=None, new_value=None, provider="file_tag_write", change_source="file_tag_write", audio_file_modified=True, reversible=False))
        db.commit()
        return {"status": "succeeded", "changed_fields": [x["field"] for x in check["fields"] if x["will_change"]]}
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
