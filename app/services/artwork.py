from __future__ import annotations

from dataclasses import dataclass
import base64
from hashlib import sha256
import os
from pathlib import Path
import struct

from mutagen import File
from mutagen.flac import Picture
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import logger
from app.database.models import Artwork, Song


FOLDER_ARTWORK_NAMES = ("cover", "folder", "front", "album")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


@dataclass(frozen=True, slots=True)
class ArtworkCandidate:
    data: bytes
    mime_type: str
    source: str


class ArtworkService:
    """Detect, deduplicate, and persist local artwork resources."""

    def __init__(self, cache_root: str | Path | None = None):
        configured = cache_root or get_settings().artwork_cache_path
        self.cache_root = Path(configured).resolve()

    def resolve_for_song(
        self,
        db: Session,
        audio_path: str | Path,
        *,
        existing_song: Song | None = None,
    ) -> Artwork | None:
        path = Path(audio_path)
        candidate = self._embedded_candidate(path)
        if candidate is not None:
            return self.cache(db, candidate)

        if existing_song is not None and existing_song.artwork is not None:
            cached = Path(existing_song.artwork.cache_path)
            if cached.is_file():
                return existing_song.artwork

        candidate = self._folder_candidate(path.parent)
        if candidate is not None:
            return self.cache(db, candidate)

        return None

    def cache(self, db: Session, candidate: ArtworkCandidate) -> Artwork:
        checksum = sha256(candidate.data).hexdigest()
        existing = db.scalar(select(Artwork).where(Artwork.checksum == checksum))
        if existing is not None:
            if not Path(existing.cache_path).is_file():
                self._write_cache(Path(existing.cache_path), candidate.data)
            return existing

        extension = _extension_for_mime(candidate.mime_type)
        cache_path = self.cache_root / checksum[:2] / f"{checksum}{extension}"
        self._write_cache(cache_path, candidate.data)
        width, height = _image_dimensions(candidate.data, candidate.mime_type)
        artwork = Artwork(
            checksum=checksum,
            cache_path=str(cache_path),
            source=candidate.source,
            mime_type=candidate.mime_type,
            width=width,
            height=height,
            file_size=len(candidate.data),
        )
        db.add(artwork)
        db.flush()
        logger.info(
            "Cached {} artwork {} at {}",
            candidate.source,
            artwork.id,
            cache_path,
        )
        return artwork

    def refresh_for_song(self, db: Session, song: Song) -> Artwork | None:
        """Re-read local artwork sources, repairing the cache when necessary."""
        path = Path(song.path)
        candidate = self._embedded_candidate(path)
        if candidate is None:
            candidate = self._folder_candidate(path.parent)

        artwork = self.cache(db, candidate) if candidate is not None else None
        if artwork is None and song.artwork is not None:
            cached = Path(song.artwork.cache_path)
            if cached.is_file():
                artwork = song.artwork

        song.artwork = artwork
        song.artwork_id = artwork.id if artwork else None
        song.artwork_status = artwork.source if artwork else "missing"
        song.cover_url = artwork_url(artwork.id) if artwork else None
        return artwork

    def _write_cache(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            return
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)

    def _embedded_candidate(self, path: Path) -> ArtworkCandidate | None:
        audio = File(path, easy=False)
        if audio is None:
            return None

        pictures = getattr(audio, "pictures", None) or []
        if pictures:
            picture = next((item for item in pictures if getattr(item, "type", None) == 3), pictures[0])
            return ArtworkCandidate(
                data=bytes(picture.data),
                mime_type=picture.mime or _sniff_mime(picture.data),
                source="embedded",
            )

        tags = audio.tags
        if tags is None:
            return None

        if getattr(tags, "getall", None):
            pictures = tags.getall("APIC")
            if pictures:
                picture = next((item for item in pictures if getattr(item, "type", None) == 3), pictures[0])
                return ArtworkCandidate(
                    data=bytes(picture.data),
                    mime_type=picture.mime or _sniff_mime(picture.data),
                    source="embedded",
                )

        covers = tags.get("covr") if hasattr(tags, "get") else None
        if covers:
            data = bytes(covers[0])
            return ArtworkCandidate(data=data, mime_type=_sniff_mime(data), source="embedded")

        encoded_pictures = (
            tags.get("metadata_block_picture") if hasattr(tags, "get") else None
        )
        if encoded_pictures:
            encoded = encoded_pictures[0] if isinstance(encoded_pictures, list) else encoded_pictures
            picture = Picture(base64.b64decode(encoded))
            return ArtworkCandidate(
                data=bytes(picture.data),
                mime_type=picture.mime or _sniff_mime(picture.data),
                source="embedded",
            )

        return None

    def _folder_candidate(self, directory: Path) -> ArtworkCandidate | None:
        expected = {
            f"{stem}{extension}".casefold(): extension
            for stem in FOLDER_ARTWORK_NAMES
            for extension in IMAGE_EXTENSIONS
        }
        candidates: dict[str, Path] = {}
        with os.scandir(directory) as entries:
            for entry in entries:
                name = entry.name.casefold()
                if name in expected and entry.is_file(follow_symlinks=False):
                    candidates[name] = Path(entry.path)
        for name, extension in expected.items():
            candidate = candidates.get(name)
            if candidate is not None:
                data = candidate.read_bytes()
                return ArtworkCandidate(data, _sniff_mime(data, extension), "folder")
        return None


def artwork_url(artwork_id: int | None) -> str | None:
    return f"/api/artwork/{artwork_id}/file" if artwork_id is not None else None


def serialize_artwork(artwork: Artwork) -> dict:
    return {
        "id": artwork.id,
        "url": artwork_url(artwork.id),
        "source": artwork.source,
        "checksum": artwork.checksum,
        "mime_type": artwork.mime_type,
        "width": artwork.width,
        "height": artwork.height,
        "file_size": artwork.file_size,
        "provider": artwork.provider,
        "provider_id": artwork.provider_id,
        "original_url": artwork.original_url,
        "created_at": artwork.created_at,
        "updated_at": artwork.updated_at,
    }


def _sniff_mime(data: bytes, extension: str | None = None) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if extension == ".png":
        return "image/png"
    if extension == ".webp":
        return "image/webp"
    return "image/jpeg"


def _extension_for_mime(mime_type: str) -> str:
    return {
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(mime_type, ".jpg")


def _image_dimensions(data: bytes, mime_type: str) -> tuple[int | None, int | None]:
    if mime_type == "image/png" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    return None, None
