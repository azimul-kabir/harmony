from __future__ import annotations

from dataclasses import dataclass
import base64
from hashlib import sha256
import os
from pathlib import Path
import struct
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

from mutagen import File
from mutagen.flac import Picture
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import logger
from app.database.models import Artwork, Song


FOLDER_ARTWORK_NAMES = ("cover", "folder", "front", "album")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
EMBEDDABLE_IMAGE_MIMES = {"image/jpeg", "image/png"}
MAX_EMBEDDED_ARTWORK_BYTES = 15 * 1024 * 1024
MAX_EMBEDDED_ARTWORK_DIMENSION = 10_000
MANUAL_ARTWORK_MIMES = {"image/jpeg", "image/png", "image/webp"}


@dataclass(frozen=True, slots=True)
class ArtworkCandidate:
    data: bytes
    mime_type: str
    source: str
    provider: str | None = None
    provider_id: str | None = None
    original_url: str | None = None


@dataclass(frozen=True, slots=True)
class MusicBrainzReleaseResolution:
    """The safe, canonical input to a Cover Art Archive release request."""

    release_id: str | None
    source_field: str | None
    outcome: str
    legacy_fallback_used: bool = False
    release_group_id: str | None = None

    @property
    def resolved(self) -> bool:
        return self.outcome == "resolved"


def resolve_musicbrainz_release_id(song: Song) -> MusicBrainzReleaseResolution:
    """Resolve only Harmony's canonical *release* identifier.

    ``Song.musicbrainz_release_id`` is the canonical value populated by metadata
    application and indexing.  There is no separate legacy release-ID column in
    the current schema, so this deliberately does not infer an ID from a release
    group, provider match, suggestion, or audio tag.
    """
    value = song.musicbrainz_release_id
    if not value or not value.strip():
        return MusicBrainzReleaseResolution(
            None,
            None,
            "release_group_only" if song.musicbrainz_release_group_id else "canonical_release_id_missing",
            release_group_id=song.musicbrainz_release_group_id,
        )
    try:
        release_id = str(UUID(value.strip()))
    except (ValueError, AttributeError):
        return MusicBrainzReleaseResolution(
            None, "songs.musicbrainz_release_id", "invalid_release_id",
            release_group_id=song.musicbrainz_release_group_id,
        )
    return MusicBrainzReleaseResolution(
        release_id, "songs.musicbrainz_release_id", "resolved",
        release_group_id=song.musicbrainz_release_group_id,
    )


class ArtworkFetchSkipped(ValueError):
    """A user-actionable non-error outcome for a remote artwork request."""

    def __init__(self, resolution: MusicBrainzReleaseResolution):
        self.resolution = resolution
        messages = {
            "canonical_release_id_missing": "Canonical MusicBrainz release ID is missing; apply canonical metadata before fetching artwork.",
            "release_group_only": "Only a MusicBrainz release-group ID is available; Cover Art Archive release lookup requires a release ID.",
            "invalid_release_id": "The canonical MusicBrainz release ID is not a valid UUID.",
        }
        super().__init__(messages.get(resolution.outcome, "Artwork fetch was skipped."))


class ArtworkValidationError(ValueError):
    """A bounded, user-safe manual artwork validation failure."""


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
            provider=candidate.provider,
            provider_id=candidate.provider_id,
            original_url=candidate.original_url,
        )
        db.add(artwork)
        db.flush()
        logger.info(
            "Cached {} artwork {}",
            candidate.source,
            artwork.id,
        )
        return artwork

    def cache_manual_upload(self, db: Session, data: bytes) -> Artwork:
        if not data:
            raise ArtworkValidationError("Choose a non-empty artwork file.")
        if len(data) > MAX_EMBEDDED_ARTWORK_BYTES:
            raise ArtworkValidationError("Artwork must be 15 MB or smaller.")
        mime_type = _recognized_image_mime(data)
        if mime_type not in MANUAL_ARTWORK_MIMES:
            raise ArtworkValidationError("Artwork must be a JPEG, PNG, or WebP image.")
        try:
            width, height = _image_dimensions(data, mime_type)
        except (ValueError, struct.error, IndexError) as error:
            raise ArtworkValidationError("Artwork is malformed or unreadable.") from error
        if not width or not height:
            raise ArtworkValidationError("Artwork dimensions could not be verified.")
        if max(width, height) > MAX_EMBEDDED_ARTWORK_DIMENSION:
            raise ArtworkValidationError("Artwork dimensions must not exceed 10,000 pixels.")
        return self.cache(db, ArtworkCandidate(data=data, mime_type=mime_type, source="manual"))

    def associate(self, song: Song, artwork: Artwork | None) -> None:
        song.artwork = artwork
        song.artwork_id = artwork.id if artwork else None
        song.artwork_status = artwork.source if artwork else "missing"
        song.cover_url = artwork_url(artwork.id) if artwork else None

    def validated_cached_bytes(self, artwork: Artwork | None) -> tuple[bytes, str] | None:
        """Return safe embeddable cache bytes without exposing its private path."""
        if artwork is None:
            return None
        try:
            data = Path(artwork.cache_path).read_bytes()
        except OSError:
            return None
        mime = _recognized_image_mime(data)
        if mime not in EMBEDDABLE_IMAGE_MIMES or len(data) > MAX_EMBEDDED_ARTWORK_BYTES:
            return None
        try:
            width, height = _image_dimensions(data, mime)
        except (ValueError, struct.error):
            return None
        if not data or not width or not height or max(width, height) > MAX_EMBEDDED_ARTWORK_DIMENSION:
            return None
        return data, mime

    def fetch_musicbrainz_release_artwork(
        self,
        db: Session,
        release_id: str,
        *,
        force_remote: bool = False,
    ) -> Artwork:
        """Download and cache the Cover Art Archive front image for a release."""
        try:
            release_id = str(UUID(release_id))
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError("A valid MusicBrainz release ID is required") from error

        existing = db.scalar(
            select(Artwork).where(
                Artwork.provider == "cover_art_archive",
                Artwork.provider_id == release_id,
            )
        )
        if existing is not None and Path(existing.cache_path).is_file() and not force_remote:
            return existing

        settings = get_settings()
        url = f"{settings.cover_art_archive_base_url.rstrip('/')}/release/{release_id}/front"
        try:
            request = Request(url, headers={"Accept": "image/jpeg, image/png, image/webp"})
            with urlopen(request, timeout=settings.cover_art_archive_timeout_seconds) as response:
                data = response.read(settings.cover_art_archive_max_bytes + 1)
                original_url = response.geturl()
        except (HTTPError, URLError, OSError) as error:
            raise ValueError("Cover Art Archive could not provide front artwork for this release") from error

        if not data or len(data) > settings.cover_art_archive_max_bytes:
            raise ValueError("Cover Art Archive returned an invalid artwork file")
        mime_type = _recognized_image_mime(data)
        if mime_type is None:
            raise ValueError("Cover Art Archive returned an unsupported artwork format")
        return self.cache(
            db,
            ArtworkCandidate(
                data=data,
                mime_type=mime_type,
                source="remote",
                provider="cover_art_archive",
                provider_id=release_id,
                original_url=original_url,
            ),
        )

    def fetch_for_song(
        self, db: Session, song: Song, *, force_remote: bool = False
    ) -> tuple[Artwork, MusicBrainzReleaseResolution, bool]:
        """Fetch canonical provider artwork, preserving a valid cached result.

        A cache hit satisfies the ordinary fetch action even when a provider ID
        is now unavailable.  Forced remote refreshes resolve and validate the
        canonical release ID before issuing a request.
        """
        cached = self.validated_cached_bytes(song.artwork)
        if cached is not None and not force_remote:
            resolution = resolve_musicbrainz_release_id(song)
            logger.info("Artwork operation=fetch_artwork song_id={} resolver_outcome={} identifier_source={} provider_response=cache_hit", song.id, resolution.outcome, resolution.source_field)
            return song.artwork, resolution, True  # type: ignore[return-value]
        resolution = resolve_musicbrainz_release_id(song)
        if not resolution.resolved:
            logger.info("Artwork operation=fetch_artwork song_id={} resolver_outcome={} identifier_source={} provider_response=not_requested cache={}", song.id, resolution.outcome, resolution.source_field, "miss" if cached is None else "hit")
            raise ArtworkFetchSkipped(resolution)
        if force_remote:
            artwork = self.fetch_musicbrainz_release_artwork(
                db, resolution.release_id, force_remote=True
            )
        else:
            artwork = self.fetch_musicbrainz_release_artwork(db, resolution.release_id)
        logger.info("Artwork operation=fetch_artwork song_id={} resolver_outcome={} identifier_source={} provider_response=success cache=miss", song.id, resolution.outcome, resolution.source_field)
        return artwork, resolution, False

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


def _recognized_image_mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _extension_for_mime(mime_type: str) -> str:
    return {
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(mime_type, ".jpg")


def _image_dimensions(data: bytes, mime_type: str) -> tuple[int | None, int | None]:
    if mime_type == "image/png" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if mime_type == "image/jpeg" and data.startswith(b"\xff\xd8"):
        pos = 2
        while pos + 9 < len(data):
            if data[pos] != 0xFF:
                raise ValueError("Malformed JPEG")
            while pos < len(data) and data[pos] == 0xFF:
                pos += 1
            marker = data[pos]; pos += 1
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                continue
            length = int.from_bytes(data[pos:pos + 2], "big")
            if length < 7 or pos + length > len(data):
                raise ValueError("Malformed JPEG")
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return int.from_bytes(data[pos + 5:pos + 7], "big"), int.from_bytes(data[pos + 3:pos + 5], "big")
            pos += length
    if mime_type == "image/webp" and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b"VP8X":
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
            return width, height
        if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
            bits = int.from_bytes(data[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
            return (
                int.from_bytes(data[26:28], "little") & 0x3FFF,
                int.from_bytes(data[28:30], "little") & 0x3FFF,
            )
    return None, None
