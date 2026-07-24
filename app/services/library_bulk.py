from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import threading
import zipfile

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import logger
from app.core.time import utcnow_naive
from app.database.models import BulkOperationItem, Song, Task
from app.database.session import SessionLocal
from app.domain.task import TaskStatus, TaskType
from app.services.artwork import ArtworkFetchSkipped, ArtworkService
from app.services.library_events import library_events
from app.services.library_scanner import index_file
from app.services.library_search import library_search
from app.services.task_service import create_task, record_item_failure


OPERATIONS = {
    "delete",
    "forget_missing",
    "move",
    "rename",
    "refresh_metadata",
    "refresh_artwork",
    "fetch_artwork",
    "export",
}
TERMINAL_ITEM_STATUSES = {"completed", "failed", "cancelled", "skipped"}
INVALID_FILENAME = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")


def _safe_operation_error(error: Exception) -> tuple[str, str]:
    """Map exceptions to bounded messages without persisting raw payloads."""
    if isinstance(error, FileExistsError):
        return "DESTINATION_EXISTS", "The destination file already exists"
    if isinstance(error, FileNotFoundError):
        return "FILE_NOT_FOUND", "The source file could not be found"
    if isinstance(error, PermissionError):
        return "FILE_PERMISSION_DENIED", "Harmony does not have permission to modify this file"
    if isinstance(error, ValueError):
        return "INVALID_FILE_OPERATION", "The file operation options or path are invalid"
    return "FILE_OPERATION_FAILED", "The file operation failed"


def create_bulk_task(
    db: Session,
    *,
    operation: str,
    song_ids: list[int],
    options: dict | None = None,
) -> Task:
    if operation not in OPERATIONS:
        raise ValueError(f"Unsupported bulk operation: {operation}")
    unique_ids = list(dict.fromkeys(song_ids))
    songs = db.scalars(select(Song).where(Song.id.in_(unique_ids))).all()
    songs_by_id = {song.id: song for song in songs}
    missing = [song_id for song_id in unique_ids if song_id not in songs_by_id]
    if missing:
        raise ValueError(f"Songs not found: {', '.join(map(str, missing))}")
    if operation == "forget_missing":
        present = [
            song.id
            for song in songs
            if song.availability_status != "missing"
        ]
        if present:
            raise ValueError(
                "Only records already marked missing can be forgotten: "
                + ", ".join(map(str, present))
            )

    task = create_task(
        db,
        name=f"Library {operation.replace('_', ' ')}",
        spotify_url=f"library://bulk/{operation}",
        task_type=TaskType.LIBRARY_BULK,
        total_items=len(songs),
        operation_payload=json.dumps({"operation": operation, "options": options or {}}),
        resource_key="library-files",
        commit=False,
    )
    for song_id in unique_ids:
        song = songs_by_id[song_id]
        task.bulk_items.append(
            BulkOperationItem(song_id=song.id, original_path=song.path, status="queued")
        )
    db.commit()
    db.refresh(task)
    logger.info("Queued Library bulk task {} ({}, {} songs)", task.id, operation, len(songs))
    return task


class LibraryBulkWorker:
    """Durable, cooperative worker for Library file operations."""

    def __init__(self, poll_seconds: float = 0.5):
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.settings = get_settings()
        self.artwork = ArtworkService()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        db = SessionLocal()
        try:
            self._recover_running(db)
        finally:
            db.close()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="library-bulk-worker",
        )
        self._thread.start()
        logger.info("Library bulk worker started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Library bulk worker stopped")

    def _run(self) -> None:
        while not self._stop.is_set():
            db = SessionLocal()
            try:
                task = db.scalar(
                    select(Task)
                    .where(
                        Task.task_type == TaskType.LIBRARY_BULK.value,
                        Task.status == TaskStatus.QUEUED.value,
                    )
                    .order_by(Task.created_at, Task.id)
                    .limit(1)
                )
                if task is not None:
                    self.process_task(db, task)
                    continue
            except Exception:
                logger.exception("Library bulk worker recovered from an unexpected failure")
                recovery_db = SessionLocal()
                try:
                    self._recover_running(recovery_db)
                except Exception:
                    logger.exception("Library bulk worker could not reset interrupted work")
                finally:
                    recovery_db.close()
            finally:
                db.close()
            self._stop.wait(self.poll_seconds)

    def _recover_running(self, db: Session) -> None:
        db.execute(
            update(Task)
            .where(
                Task.task_type == TaskType.LIBRARY_BULK.value,
                Task.status.in_((TaskStatus.RUNNING.value, TaskStatus.CANCELLING.value)),
            )
            .values(status=TaskStatus.INTERRUPTED.value, current_item=None, completed_at=utcnow_naive())
        )
        db.execute(
            update(BulkOperationItem)
            .where(BulkOperationItem.status == "running")
            .values(status="queued", started_at=None)
        )
        db.commit()

    def process_task(self, db: Session, task: Task) -> None:
        payload = json.loads(task.operation_payload or "{}")
        operation = payload.get("operation")
        options = payload.get("options") or {}
        task.status = TaskStatus.RUNNING.value
        task.started_at = task.started_at or utcnow_naive()
        db.commit()

        archive: zipfile.ZipFile | None = None
        if operation == "export":
            export_root = Path(self.settings.download_path).resolve() / "exports"
            export_root.mkdir(parents=True, exist_ok=True)
            archive_path = export_root / f"harmony-library-{task.id}.zip"
            task.output_path = str(archive_path)
            db.commit()
            archive = zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED)

        try:
            items = db.scalars(
                select(BulkOperationItem)
                .where(
                    BulkOperationItem.task_id == task.id,
                    BulkOperationItem.status == "queued",
                )
                .order_by(BulkOperationItem.id)
            ).all()
            for item in items:
                db.refresh(task)
                if task.status in (TaskStatus.CANCELLED.value, TaskStatus.CANCELLING.value) or self._stop.is_set():
                    if self._stop.is_set() and task.status not in (TaskStatus.CANCELLED.value, TaskStatus.CANCELLING.value):
                        task.status = TaskStatus.INTERRUPTED.value
                        task.recovery_metadata = '{"reason":"worker_shutdown"}'
                        task.completed_at = utcnow_naive()
                        task.current_item = None
                        db.commit()
                        return
                    self._cancel_remaining(db, task)
                    task.status = TaskStatus.CANCELLED.value
                    task.completed_at = utcnow_naive()
                    db.commit()
                    return
                if task.status == TaskStatus.PAUSED.value:
                    return

                item.status = "running"
                item.started_at = utcnow_naive()
                task.current_item = Path(item.original_path).name
                db.commit()
                try:
                    item.result_path = self._apply(db, item, operation, options, archive)
                    item.status = "completed"
                    task.completed_items += 1
                except ArtworkFetchSkipped as error:
                    # Missing/invalid provider metadata is actionable but is not a
                    # filesystem or provider failure.  Keep it visible as a
                    # structured skipped item rather than masking it as a generic
                    # file-operation error.
                    item.status = "skipped"
                    item.error = str(error)
                    task.skipped_items += 1
                    logger.info(
                        "Artwork operation={} song_id={} resolver_outcome={} identifier_source={} provider_response=skipped",
                        operation, item.song_id, error.resolution.outcome,
                        error.resolution.source_field,
                    )
                except Exception as error:
                    db.rollback()
                    # Filesystem operations cannot be rolled back by SQLite.
                    # Reconcile the canonical row before reporting a failed
                    # item so retries/restarts never retain stale availability.
                    self._reconcile_item(db, item)
                    task = db.get(Task, task.id)
                    item = db.get(BulkOperationItem, item.id)
                    error_code, error_message = _safe_operation_error(error)
                    item.status = "failed"
                    item.error = error_message
                    task.failed_items += 1
                    record_item_failure(db, task, Path(item.original_path).name, error_code, error_message)
                    logger.exception("Library bulk task {} failed for {}", task.id, item.original_path)
                item.completed_at = utcnow_naive()
                db.commit()
        finally:
            if archive is not None:
                archive.close()

        db.refresh(task)
        if task.status == TaskStatus.CANCELLED.value:
            self._cancel_remaining(db, task)
            return
        if operation == "delete" and task.completed_items:
            spotify_ids = db.scalars(
                select(Song.spotify_track_id)
                .join(
                    BulkOperationItem,
                    BulkOperationItem.song_id == Song.id,
                )
                .where(
                    BulkOperationItem.task_id == task.id,
                    BulkOperationItem.status == "completed",
                    Song.spotify_track_id.is_not(None),
                )
            ).all()
            from app.services.playlist_manager import export_m3us_for_tracks

            export_m3us_for_tracks(db, list(spotify_ids))
        task.current_item = None
        task.completed_at = utcnow_naive()
        if task.failed_items and not task.completed_items:
            task.status = TaskStatus.FAILED.value
        elif task.failed_items:
            task.status = TaskStatus.COMPLETED_WITH_ERRORS.value
        else:
            task.status = TaskStatus.COMPLETED.value
        db.commit()
        logger.info(
            "Library bulk task {} finished: {} completed, {} failed",
            task.id,
            task.completed_items,
            task.failed_items,
        )

    def _reconcile_item(self, db: Session, item: BulkOperationItem) -> None:
        song = db.get(Song, item.song_id) if item.song_id else None
        if song is None:
            return
        try:
            index_file(db, song.path, force=False, commit=False)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Could not reconcile failed bulk item {}", item.id)

    def _cancel_remaining(self, db: Session, task: Task) -> None:
        remaining = db.scalars(
            select(BulkOperationItem).where(
                BulkOperationItem.task_id == task.id,
                BulkOperationItem.status == "queued",
            )
        ).all()
        now = utcnow_naive()
        for item in remaining:
            item.status = "cancelled"
            item.completed_at = now
        task.skipped_items += len(remaining)
        task.current_item = None
        db.commit()

    def _apply(
        self,
        db: Session,
        item: BulkOperationItem,
        operation: str,
        options: dict,
        archive: zipfile.ZipFile | None,
    ) -> str | None:
        song = db.get(Song, item.song_id) if item.song_id else None
        if song is None:
            raise FileNotFoundError("Library song no longer exists")
        source = self._managed_path(song.path)

        if operation == "delete":
            try:
                source.unlink()
            except FileNotFoundError:
                # Deletion is idempotent: a stale index path means the
                # filesystem side of the operation is already complete.
                pass
            # Retain the durable row and its provenance after deletion.
            song.availability_status = "missing"
            song.last_indexed_at = utcnow_naive()
            db.flush()
            library_events.publish("library.track.missing", path=str(source), song_id=song.id)
            return None
        if operation == "forget_missing":
            if song.availability_status != "missing":
                raise ValueError("Only a missing Library record can be forgotten")
            try:
                source.stat()
            except FileNotFoundError:
                pass
            else:
                raise ValueError(
                    "The indexed file exists again; refresh the Library instead"
                )
            song_id = song.id
            # The durable task item must survive after its Song is forgotten.
            item.song_id = None
            db.delete(song)
            db.flush()
            library_search.index_song(db, song_id)
            library_events.publish(
                "library.track.forgotten",
                path=str(source),
                song_id=song_id,
            )
            return None
        if operation == "move":
            destination_dir = self._managed_path(options.get("destination", ""), relative=True)
            destination_dir.mkdir(parents=True, exist_ok=True)
            return self._move_and_reindex(db, song, source, destination_dir / source.name)
        if operation == "rename":
            filename = self._render_filename(song, source, options.get("pattern", "{track} - {title}{ext}"))
            return self._move_and_reindex(db, song, source, source.with_name(filename))
        if operation == "refresh_metadata":
            result = index_file(db, source, force=True, commit=False)
            library_events.publish("library.track.updated", path=str(source), song_id=result.song_id)
            return str(source)
        if operation == "refresh_artwork":
            self.artwork.refresh_for_song(db, song)
            library_events.publish("library.track.updated", path=str(source), song_id=song.id)
            return str(source)
        if operation == "fetch_artwork":
            artwork, _resolution, _cache_hit = self.artwork.fetch_for_song(
                db, song, force_remote=bool(options.get("force_remote", False))
            )
            song.artwork = artwork
            song.artwork_id = artwork.id
            song.artwork_status = artwork.source
            song.cover_url = f"/api/artwork/{artwork.id}/file"
            library_events.publish("library.track.updated", path=str(source), song_id=song.id)
            return str(source)
        if operation == "export":
            if archive is None:
                raise RuntimeError("Export archive is unavailable")
            root = Path(self.settings.music_path).resolve()
            archive.write(source, arcname=str(source.relative_to(root)))
            return str(source)
        raise ValueError(f"Unsupported bulk operation: {operation}")

    def _managed_path(self, value: str, *, relative: bool = False) -> Path:
        root = Path(self.settings.music_path).resolve()
        path = (root / value).resolve() if relative else Path(value).resolve()
        if path != root and not path.is_relative_to(root):
            raise ValueError("Path must remain inside the configured music folder")
        return path

    def _move_and_reindex(self, db: Session, song: Song, source: Path, destination: Path) -> str:
        destination = self._managed_path(str(destination))
        if destination == source:
            return str(source)
        if destination.exists():
            raise FileExistsError(f"Destination already exists: {destination.name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        try:
            song.path = str(destination)
            song.filename = destination.name
            db.flush()
            result = index_file(db, destination, force=True, commit=False)
        except Exception:
            if destination.exists() and not source.exists():
                shutil.move(str(destination), str(source))
            raise
        library_events.publish(
            "library.track.renamed",
            old_path=str(source),
            path=str(destination),
            song_id=result.song_id,
        )
        return str(destination)

    def _render_filename(self, song: Song, source: Path, pattern: str) -> str:
        values = {
            "artist": song.artist or "Unknown Artist",
            "album": song.album or "Unknown Album",
            "title": song.title or source.stem,
            "track": f"{song.track:02d}" if song.track is not None else "00",
            "disc": str(song.disc or 1),
            "filename": source.stem,
            "ext": source.suffix,
        }
        try:
            filename = pattern.format_map(values).strip()
        except (KeyError, ValueError) as error:
            raise ValueError(f"Invalid rename pattern: {error}") from error
        filename = INVALID_FILENAME.sub("_", filename)
        if not filename.endswith(source.suffix):
            filename += source.suffix
        if filename in {"", ".", ".."}:
            raise ValueError("Rename pattern produced an invalid filename")
        return filename


library_bulk_worker = LibraryBulkWorker()
