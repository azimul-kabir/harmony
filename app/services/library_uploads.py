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

from app.core.config import get_settings
from app.core.logging import logger
from app.exceptions.library import DuplicateTrackError, MetadataReadError
from app.services.import_engine import import_download
from app.services.library_paths import build_destination
from app.services.metadata import read_metadata
from app.services.metadata_editor import write_metadata


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
        summaries.append({
            "id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
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
        })
    summaries.sort(key=lambda group: group["label"].casefold())
    return {"groups": summaries, "group_count": len(summaries), "finding_count": sum(len(group["findings"]) for group in summaries)}


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


def cleanup_expired_batches(*, max_age_seconds: int = 24 * 60 * 60) -> int:
    """Remove abandoned private upload batches without touching active Library files."""
    root = upload_root()
    if not root.exists():
        return 0
    cutoff = time.time() - max_age_seconds
    removed = 0
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        try:
            created_at = int(load_batch(directory.name).get("created_at", 0))
        except UploadValidationError:
            created_at = int(directory.stat().st_mtime)
        if created_at and created_at < cutoff:
            shutil.rmtree(directory, ignore_errors=True)
            removed += 1
    return removed
