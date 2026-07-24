from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import os
from pathlib import Path

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import logger
from app.core.time import utcnow_naive
from app.database.crud import UpsertStatus, upsert_song
from app.database.models import Song
from app.services.artwork import ArtworkService, artwork_url
from app.services.library_search import library_search
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
    for directory, _, filenames in os.walk(root, followlinks=False):
        base = Path(directory)
        for filename in filenames:
            if Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS:
                yield base / filename


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
            song.last_indexed_at = utcnow_naive()
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
    # A watcher must never erase a richer canonical genre merely because an
    # external editor removed (or cannot represent) the embedded tag.
    if song is not None and song.genre and not metadata.get("genre"):
        metadata["genre"] = song.genre
    metadata.update(
        {
            "path": path_string,
            "filename": path.name,
            "last_modified": datetime.fromtimestamp(stat.st_mtime, UTC).replace(
                tzinfo=None
            ),
            "last_indexed_at": utcnow_naive(),
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
    db.flush()
    library_search.index_song(db, song.id)

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

    # Callers treat a scan as a committing operation. Close any read snapshot
    # they opened so each file can acquire a fresh SQLite writer reservation.
    db.commit()

    for file in iter_music_files(library_root):
        result.discovered += 1
        found.add(str(file.resolve()))
        try:
            # In WAL mode a transaction that reads first cannot always upgrade
            # after another connection writes (SQLITE_BUSY_SNAPSHOT). Reserve
            # the one SQLite writer before index_file performs its first SELECT.
            db.execute(text("BEGIN IMMEDIATE"))
            with db.begin_nested():
                indexed = index_file(db, file, force=force, commit=False)
            # A rebuild can run for many minutes. Keep each file as the atomic
            # reconciliation unit so SQLite's single writer is released between
            # files for download workers and other short-lived writes.
            db.commit()
            setattr(result, indexed.status, getattr(result, indexed.status) + 1)
        except Exception:
            db.rollback()
            result.failed += 1
            logger.exception("Failed to index {}", file)

    now = utcnow_naive()
    missing_ids: list[int] = []
    existing = db.execute(
        select(Song.id, Song.path, Song.availability_status)
        .execution_options(yield_per=1000)
    )
    for song_id, path, availability_status in existing:
        try:
            song_path = Path(path).resolve()
            managed = song_path.is_relative_to(library_root)
        except (OSError, ValueError):
            managed = False

        if managed and str(song_path) not in found and availability_status != "missing":
            missing_ids.append(song_id)

    for start in range(0, len(missing_ids), 500):
        batch = missing_ids[start:start + 500]
        db.execute(
            update(Song)
            .where(Song.id.in_(batch))
            .values(availability_status="missing", last_indexed_at=now)
        )
    result.missing = len(missing_ids)

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
