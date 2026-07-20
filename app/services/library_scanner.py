from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import logger
from app.database.crud import UpsertStatus, upsert_song
from app.database.models import Song
from app.services.artwork import ArtworkService, artwork_url
from app.services.metadata import read_metadata
from app.services.tags import SUPPORTED_EXTENSIONS

settings = get_settings()
artwork_service = ArtworkService()


@dataclass(slots=True)
class IndexResult:
    path: str
    status: str
    song_id: int | None = None
    error: str | None = None


@dataclass(slots=True)
class ScanResult:
    discovered: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    missing: int = 0
    failed: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def iter_music_files(root: Path):
    if not root.exists():
        return

    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def index_file(
    db: Session,
    file: str | Path,
    *,
    force: bool = False,
    cover_url: str | None = None,
    download_source: str | None = None,
    commit: bool = True,
) -> IndexResult:
    path = Path(file).resolve()
    path_string = str(path)
    song = db.scalar(select(Song).where(Song.path == path_string))

    if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        if song is not None:
            song.availability_status = "missing"
            song.last_indexed_at = datetime.now(UTC).replace(tzinfo=None)
            if commit:
                db.commit()
            return IndexResult(path=path_string, status="missing", song_id=song.id)
        return IndexResult(path=path_string, status="missing")

    stat = path.stat()
    current_mtime = int(stat.st_mtime)

    if (
        song is not None
        and not force
        and song.availability_status == "available"
        and song.modified_time == current_mtime
        and song.file_size == stat.st_size
    ):
        return IndexResult(path=path_string, status="unchanged", song_id=song.id)

    metadata = read_metadata(path)
    metadata.update(
        {
            "path": path_string,
            "filename": path.name,
            "last_modified": datetime.fromtimestamp(stat.st_mtime, UTC).replace(
                tzinfo=None
            ),
            "last_indexed_at": datetime.now(UTC).replace(tzinfo=None),
            "availability_status": "available",
        }
    )

    try:
        artwork = artwork_service.resolve_for_song(db, path, existing_song=song)
    except Exception:
        artwork = None
        logger.exception("Failed to resolve local artwork for {}", path)

    if artwork is not None:
        metadata["artwork_id"] = artwork.id
        metadata["artwork_status"] = artwork.source
        metadata["cover_url"] = artwork_url(artwork.id)

    if cover_url and artwork is None:
        metadata["cover_url"] = cover_url
        if metadata["artwork_status"] == "missing":
            metadata["artwork_status"] = "remote"
    elif (
        song is not None
        and song.cover_url
        and metadata["artwork_status"] == "missing"
        and artwork is None
    ):
        metadata["artwork_status"] = "remote"

    if download_source:
        metadata["download_source"] = download_source
    elif song is None:
        metadata["download_source"] = "filesystem"

    previous_hash = song.metadata_hash if song is not None else None
    previous_mtime = song.modified_time if song is not None else None
    previous_size = song.file_size if song is not None else None
    previous_availability = song.availability_status if song is not None else None
    upsert_status, song = upsert_song(db, metadata, commit=False)

    if commit:
        db.commit()
        db.refresh(song)

    if upsert_status == UpsertStatus.NEW:
        status = "added"
    elif (
        previous_hash != song.metadata_hash
        or previous_mtime != song.modified_time
        or previous_size != song.file_size
        or previous_availability != "available"
    ):
        status = "updated"
    else:
        status = "unchanged"

    return IndexResult(path=path_string, status=status, song_id=song.id)


def scan_library(
    db: Session,
    root: str | Path | None = None,
    *,
    force: bool = False,
) -> ScanResult:
    library_root = Path(root or settings.music_path).resolve()
    result = ScanResult()
    found: set[str] = set()

    logger.info("Indexing library {}", library_root)

    for file in iter_music_files(library_root):
        result.discovered += 1
        found.add(str(file.resolve()))
        try:
            with db.begin_nested():
                indexed = index_file(db, file, force=force, commit=False)
            setattr(result, indexed.status, getattr(result, indexed.status) + 1)
        except Exception:
            result.failed += 1
            logger.exception("Failed to index {}", file)

    existing = db.scalars(select(Song)).all()
    now = datetime.now(UTC).replace(tzinfo=None)
    for song in existing:
        try:
            song_path = Path(song.path).resolve()
            managed = song_path.is_relative_to(library_root)
        except (OSError, ValueError):
            managed = False

        if managed and str(song_path) not in found and song.availability_status != "missing":
            song.availability_status = "missing"
            song.last_indexed_at = now
            result.missing += 1

    db.commit()
    logger.info("Library indexing complete: {}", result.to_dict())
    return result


def scan_file(
    db: Session,
    file: Path,
    cover_url: str | None = None,
    download_source: str | None = None,
):
    """Compatibility wrapper for the previous single-file scanner."""
    return index_file(
        db,
        file,
        force=True,
        cover_url=cover_url,
        download_source=download_source,
    )
