"""Staged, review-first imports for user-supplied audio files."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import time
from typing import BinaryIO
from uuid import UUID, uuid4

from mutagen import File as MutagenFile
from sqlalchemy.orm import Session
from sqlalchemy import or_, select

from app.core.config import get_settings
from app.core.logging import logger
from app.exceptions.library import DuplicateTrackError, MetadataReadError
from app.services.import_engine import import_download
from app.services.library_paths import build_destination
from app.services.metadata import read_metadata
from app.services.metadata_editor import write_metadata
from app.services.artwork import ArtworkService
from app.database.models import Artwork, Song
from app.services.duplicate_detector import _normal


SUPPORTED_AUDIO_EXTENSIONS = {".flac", ".m4a", ".mp3", ".mp4", ".ogg", ".opus"}
CHUNK_SIZE = 1024 * 1024
PROMOTIONAL_WORDS = re.compile(
    r"(?i)\b(downloaded\s+from|free\s+download|visit\s+(?:us|our)|follow\s+us|"
    r"telegram|whatsapp|official\s+website)\b"
)
URL = re.compile(r"(?i)(?:https?://|www\.)\S+|\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+\b")
WRAPPED_BRANDING = re.compile(
    r"\s*[\[(](?:[^\])]*(?:download|www\.|https?://|\.(?:com|net|org))[^\])]*?)[\])]\s*",
    re.IGNORECASE,
)


class UploadValidationError(ValueError):
    pass


def upload_root() -> Path:
    return Path(get_settings().staging_path) / "library-uploads"


def _batch_dir(batch_id: str) -> Path:
    try:
        normalized = str(UUID(batch_id))
    except (ValueError, TypeError) as error:
        raise UploadValidationError("Invalid upload batch.") from error
    root = upload_root().resolve()
    path = (root / normalized).resolve()
    if path.parent != root:
        raise UploadValidationError("Invalid upload batch.")
    return path


def create_batch() -> dict:
    batch_id = str(uuid4())
    directory = _batch_dir(batch_id)
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {"id": batch_id, "created_at": int(time.time()), "items": []}
    _write_manifest(directory, manifest)
    return manifest


def load_batch(batch_id: str) -> dict:
    path = _batch_dir(batch_id) / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise UploadValidationError("Upload batch was not found or has expired.") from error
    if manifest.get("id") != batch_id or not isinstance(manifest.get("items"), list):
        raise UploadValidationError("Upload batch is invalid.")
    return manifest


def _write_manifest(directory: Path, manifest: dict) -> None:
    temporary = directory / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, directory / "manifest.json")


def safe_upload_name(filename: str | None) -> str:
    name = Path((filename or "").replace("\\", "/")).name.strip()
    if not name or name in {".", ".."}:
        raise UploadValidationError("Every upload must have a filename.")
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_AUDIO_EXTENSIONS:
        raise UploadValidationError(f"Unsupported audio type: {suffix or 'no extension'}")
    return name[:500]


def save_upload(batch_id: str, filename: str | None, stream: BinaryIO, *, max_bytes: int) -> dict:
    manifest = load_batch(batch_id)
    if len(manifest["items"]) >= get_settings().library_upload_max_files:
        raise UploadValidationError("This batch contains too many files.")
    original_name = safe_upload_name(filename)
    item_id = str(uuid4())
    staged_path = _batch_dir(batch_id) / f"{item_id}{Path(original_name).suffix.lower()}"
    size = 0
    try:
        with staged_path.open("xb") as target:
            while chunk := stream.read(CHUNK_SIZE):
                size += len(chunk)
                if size > max_bytes:
                    raise UploadValidationError("The uploaded file exceeds the configured size limit.")
                target.write(chunk)
        metadata = read_metadata(staged_path)
    except Exception:
        staged_path.unlink(missing_ok=True)
        raise
    analysis = analyze_metadata(metadata, original_name=original_name, path=staged_path)
    item = {
        "id": item_id,
        "original_name": original_name,
        "staged_name": staged_path.name,
        "size": size,
        "metadata": _public_metadata(metadata),
        "proposed": analysis["proposed"],
        "changes": analysis["changes"],
        "warnings": analysis["warnings"],
        "destination": str(build_destination({**metadata, **analysis["proposed"]})),
    }
    manifest["items"].append(item)
    _write_manifest(_batch_dir(batch_id), manifest)
    return item


def _public_metadata(metadata: dict) -> dict:
    keys = (
        "title", "artist", "album_artist", "album", "genre", "year", "track", "disc",
        "duration", "bitrate", "codec", "sample_rate", "artwork_status", "isrc",
        "musicbrainz_recording_id", "spotify_track_id",
    )
    return {key: metadata.get(key) for key in keys}


def summarize_batch(manifest: dict) -> dict:
    """Return album-oriented review groups without trusting browser grouping."""
    groups: dict[str, list[dict]] = {}
    for item in manifest.get("items", []):
        metadata = item.get("proposed") or item.get("metadata") or {}
        album = (metadata.get("album") or "").strip()
        artist = (metadata.get("album_artist") or metadata.get("artist") or "Unknown Artist").strip()
        identity = album.casefold() if album else f"__singles__:{artist.casefold()}"
        groups.setdefault(identity, []).append(item)

    summaries = []
    for identity, items in groups.items():
        values = [item.get("proposed") or item.get("metadata") or {} for item in items]
        album = next((value.get("album") for value in values if value.get("album")), None)
        artists = sorted({value.get("album_artist") or value.get("artist") for value in values if value.get("album_artist") or value.get("artist")}, key=str.casefold)
        years = sorted({value.get("year") for value in values if value.get("year") is not None})
        genres = sorted({value.get("genre") for value in values if value.get("genre")}, key=str.casefold)
        tracks = [value.get("track") for value in values if value.get("track") is not None]
        findings = []
        if len(artists) > 1:
            findings.append("Album artist is inconsistent across this group.")
        if len(years) > 1:
            findings.append("Year is inconsistent across this group.")
        if len(genres) > 1:
            findings.append("Genre is inconsistent across this group.")
        if len(tracks) != len(items):
            findings.append("One or more tracks have no track number.")
        if len(tracks) != len(set(tracks)):
            findings.append("Duplicate track numbers were detected.")
        if tracks and len(tracks) == len(set(tracks)):
            expected = set(range(min(tracks), max(tracks) + 1))
            if set(tracks) != expected:
                findings.append("The track-number sequence has gaps.")
        group_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        summaries.append({
            "id": group_id,
            "album": album,
            "label": album or f"Singles · {artists[0] if artists else 'Unknown Artist'}",
            "item_ids": [item["id"] for item in items],
            "track_count": len(items),
            "values": {
                "album": album,
                "album_artist": artists[0] if len(artists) == 1 else None,
                "year": years[0] if len(years) == 1 else None,
                "genre": genres[0] if len(genres) == 1 else None,
            },
            "findings": findings,
            "artwork": (manifest.get("artwork") or {}).get(group_id),
        })
    summaries.sort(key=lambda group: group["label"].casefold())
    return {"groups": summaries, "group_count": len(summaries), "finding_count": sum(len(group["findings"]) for group in summaries)}


def set_batch_artwork(batch_id: str, group_id: str, artwork: Artwork | None) -> dict:
    manifest = load_batch(batch_id)
    group = next((item for item in summarize_batch(manifest)["groups"] if item["id"] == group_id), None)
    if group is None:
        raise UploadValidationError("Album group was not found.")
    artwork_map = manifest.setdefault("artwork", {})
    if artwork is None:
        artwork_map.pop(group_id, None)
    else:
        artwork_map[group_id] = {"id": artwork.id, "mime_type": artwork.mime_type, "url": f"/api/artwork/{artwork.id}/file"}
    _write_manifest(_batch_dir(batch_id), manifest)
    return next(item for item in summarize_batch(manifest)["groups"] if item["id"] == group_id)


def duplicate_preflight(db: Session, manifest: dict) -> dict:
    """Compare staged identities with a bounded set of available Library rows."""
    results = []
    for item in manifest.get("items", []):
        metadata = item.get("proposed") or item.get("metadata") or {}
        clauses = [Song.path == item.get("destination")]
        for field in ("musicbrainz_recording_id", "isrc", "spotify_track_id"):
            value = (item.get("metadata") or {}).get(field)
            if value:
                clauses.append(getattr(Song, field) == value)
        if metadata.get("artist") and metadata.get("title"):
            # Title-only SQL blocking keeps the candidate set bounded while
            # Python normalization handles accents and punctuation reliably.
            title_token = _normal(metadata["title"]).split(" ")[0]
            if title_token:
                clauses.append(Song.title.ilike(f"%{title_token}%"))
        candidates = list(db.scalars(
            select(Song).where(Song.availability_status == "available", or_(*clauses)).order_by(Song.id).limit(20)
        ).all())
        matches = []
        staged_ids = item.get("metadata") or {}
        for song in candidates:
            tier = evidence = None
            if item.get("destination") == song.path:
                tier, evidence = "exact", "Same canonical destination"
            elif staged_ids.get("musicbrainz_recording_id") and _normal(staged_ids["musicbrainz_recording_id"]) == _normal(song.musicbrainz_recording_id):
                tier, evidence = "exact", "Same MusicBrainz recording ID"
            elif staged_ids.get("spotify_track_id") and _normal(staged_ids["spotify_track_id"]) == _normal(song.spotify_track_id):
                tier, evidence = "exact", "Same Spotify track ID"
            elif staged_ids.get("isrc") and _normal(staged_ids["isrc"]) == _normal(song.isrc):
                tier, evidence = "strong", "Same ISRC"
            elif _normal(metadata.get("artist")) == _normal(song.artist) and _normal(metadata.get("title")) == _normal(song.title):
                conflicts = any(staged_ids.get(field) and getattr(song, field) and _normal(staged_ids[field]) != _normal(getattr(song, field)) for field in ("musicbrainz_recording_id", "isrc", "spotify_track_id"))
                if conflicts:
                    continue
                duration = (item.get("metadata") or {}).get("duration")
                if duration is not None and song.duration is not None and abs(duration - song.duration) <= 3:
                    tier, evidence = "probable", f"Same artist/title; duration differs by {abs(duration-song.duration):.1f}s"
                elif _normal(metadata.get("album")) and _normal(metadata.get("album")) == _normal(song.album):
                    tier, evidence = "possible", "Same artist, title, and album"
            if tier:
                matches.append({"song_id": song.id, "tier": tier, "evidence": evidence, "title": song.title, "artist": song.artist, "album": song.album, "filename": song.filename, "duration": song.duration, "bitrate": song.bitrate, "cover_url": song.cover_url})
        if matches:
            matches.sort(key=lambda match: ({"exact": 0, "strong": 1, "probable": 2, "possible": 3}[match["tier"]], match["song_id"]))
            results.append({"item_id": item["id"], "recommended_action": "skip" if matches[0]["tier"] in {"exact", "strong"} else "review", "matches": matches})
    return {"items": results, "match_count": sum(len(item["matches"]) for item in results)}


def _clean_text(value: str | None) -> tuple[str | None, list[str]]:
    if not value:
        return value, []
    original = str(value)
    cleaned = WRAPPED_BRANDING.sub(" ", original)
    parts = re.split(r"\s+(?:[-–—|•]+)\s+", cleaned)
    kept = [part for part in parts if not URL.search(part) and not PROMOTIONAL_WORDS.search(part)]
    if kept:
        cleaned = " - ".join(kept)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—|•_\t")
    reasons = ["Removed likely download-site branding"] if cleaned != original else []
    return cleaned or None, reasons


def _tag_text(value) -> str:
    if hasattr(value, "text"):
        value = value.text
    if isinstance(value, (list, tuple)):
        return "\n".join(str(item) for item in value)
    return str(value)


def _auxiliary_action(key: str, text: str) -> tuple[str | None, str | None]:
    normalized = key.casefold()
    suspicious = bool(URL.search(text) or PROMOTIONAL_WORDS.search(text))
    if not suspicious:
        return None, None
    if normalized.startswith(("comm", "w", "tenc", "©cmt", "©too")) or normalized in {
        "comment", "comments", "description", "encodedby", "encoder", "organization",
        "publisher", "purl", "url", "website",
    }:
        return "remove", None
    if normalized.startswith("uslt") or normalized in {"lyrics", "unsyncedlyrics", "©lyr"}:
        lines = text.splitlines()
        cleaned = "\n".join(
            line for line in lines if not URL.search(line) and not PROMOTIONAL_WORDS.search(line)
        ).strip()
        return "rewrite", cleaned
    return None, None


def sanitize_auxiliary_tags(path: Path, *, apply: bool = False) -> list[dict]:
    audio = MutagenFile(path, easy=False)
    tags = getattr(audio, "tags", None)
    if audio is None or tags is None or not hasattr(tags, "keys"):
        return []
    changes = []
    for key in list(tags.keys()):
        try:
            value = tags[key]
            text = _tag_text(value)
        except Exception:
            continue
        action, replacement = _auxiliary_action(str(key), text)
        if action is None:
            continue
        changes.append({
            "field": str(key),
            "before": text[:500],
            "after": (replacement or "")[:500] or None,
            "reason": "Removed promotional metadata" if action == "remove" else "Removed branded lyric lines",
        })
        if not apply:
            continue
        if action == "remove" or not replacement:
            del tags[key]
        elif hasattr(value, "text"):
            value.text = replacement
        elif isinstance(value, list):
            tags[key] = [replacement]
        else:
            tags[key] = replacement
    if apply and changes:
        audio.save()
    return changes


def analyze_metadata(metadata: dict, *, original_name: str, path: Path | None = None) -> dict:
    proposed = {}
    changes = []
    warnings = []
    for field in ("title", "artist", "album_artist", "album", "genre"):
        original = metadata.get(field)
        cleaned, reasons = _clean_text(original)
        proposed[field] = cleaned
        if cleaned != original:
            changes.append({"field": field, "before": original, "after": cleaned, "reason": reasons[0]})
    for field in ("year", "track", "disc"):
        proposed[field] = metadata.get(field)
    if not proposed.get("title"):
        filename_title, _ = _clean_text(Path(original_name).stem)
        proposed["title"] = filename_title
        warnings.append("Title is missing; review the filename-derived title.")
    if not proposed.get("artist"):
        warnings.append("Artist is missing; this file will be organized under Unknown Artist.")
    if not proposed.get("album"):
        warnings.append("Album is missing; this file will be organized under Singles.")
    if not proposed.get("album_artist"):
        proposed["album_artist"] = proposed.get("artist")
    if path is not None:
        changes.extend(sanitize_auxiliary_tags(path))
    return {"proposed": proposed, "changes": changes, "warnings": warnings}


def import_batch(db: Session, batch_id: str, selections: list[dict]) -> dict:
    manifest = load_batch(batch_id)
    summary = summarize_batch(manifest)
    artwork_by_item = {
        item_id: group.get("artwork")
        for group in summary["groups"] for item_id in group["item_ids"]
    }
    by_id = {item["id"]: item for item in manifest["items"]}
    results = []
    imported = 0
    seen = set()
    for selection in selections:
        if selection.get("id") in seen:
            results.append({"id": selection.get("id"), "status": "failed", "error": "Upload item was selected more than once."})
            continue
        seen.add(selection.get("id"))
        item = by_id.get(selection.get("id"))
        if item is None:
            results.append({"id": selection.get("id"), "status": "failed", "error": "Upload item not found."})
            continue
        staged_path = _batch_dir(batch_id) / item["staged_name"]
        values = {**item["proposed"], **(selection.get("metadata") or {})}
        try:
            sanitize_auxiliary_tags(staged_path, apply=True)
            write_metadata(staged_path, values)
            artwork_ref = artwork_by_item.get(item["id"])
            if artwork_ref:
                artwork = db.get(Artwork, artwork_ref["id"])
                if artwork is None:
                    raise UploadValidationError("Selected album artwork is no longer available.")
                ArtworkService().embed(staged_path, artwork)
            # A successful read-back proves the container remains parseable after tag mutation.
            verified = read_metadata(staged_path)
            if not verified.get("title"):
                raise UploadValidationError("A title is required before import.")
            destination = import_download(db, staged_path, download_source="web_upload")
            results.append({"id": item["id"], "status": "imported", "destination": str(destination)})
            imported += 1
        except DuplicateTrackError:
            db.rollback()
            results.append({"id": item["id"], "status": "failed", "error": "A file already exists at the proposed Library location."})
        except (MetadataReadError, UploadValidationError, ValueError) as error:
            db.rollback()
            results.append({"id": item["id"], "status": "failed", "error": str(error)})
        except Exception:
            db.rollback()
            logger.exception("Local Library import failed for staged item {}", item["id"])
            results.append({"id": item["id"], "status": "failed", "error": "Harmony could not safely import this file."})
    imported_ids = {item["id"] for item in results if item["status"] == "imported"}
    manifest["items"] = [item for item in manifest["items"] if item["id"] not in imported_ids]
    if not manifest["items"]:
        shutil.rmtree(_batch_dir(batch_id), ignore_errors=True)
    elif imported_ids:
        _write_manifest(_batch_dir(batch_id), manifest)
    return {"batch_id": batch_id, "imported": imported, "total": len(selections), "items": results}


def discard_batch(batch_id: str) -> None:
    directory = _batch_dir(batch_id)
    if not directory.exists():
        raise UploadValidationError("Upload batch was not found or has expired.")
    shutil.rmtree(directory)


def cleanup_expired_batches(*, max_age_seconds: int = 24 * 60 * 60, protected_batch_ids: set[str] | None = None) -> int:
    """Remove abandoned private upload batches without touching active Library files."""
    root = upload_root()
    if not root.exists():
        return 0
    cutoff = time.time() - max_age_seconds
    protected_batch_ids = protected_batch_ids or set()
    removed = 0
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        if directory.name in protected_batch_ids:
            continue
        try:
            created_at = int(load_batch(directory.name).get("created_at", 0))
        except UploadValidationError:
            created_at = int(directory.stat().st_mtime)
        if created_at and created_at < cutoff:
            shutil.rmtree(directory, ignore_errors=True)
            removed += 1
    return removed
