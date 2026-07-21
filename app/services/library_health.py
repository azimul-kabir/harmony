from __future__ import annotations

import json
from pathlib import Path
import threading

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import logger
from app.core.time import utcnow_naive
from app.database.models import Artwork, Song, Task
from app.database.session import SessionLocal
from app.database.pagination import iter_primary_keys
from app.domain.task import TaskStatus, TaskType
from app.services.library_analytics import library_analytics
from app.services.library_events import library_events
from app.services.library_scanner import index_file, scan_library
from app.services.library_search import library_search
from app.services.library_predicates import missing_metadata_expression
from app.services.task_service import create_task


HEALTH_ACTIONS = {
    "refresh": "Refresh Library",
    "rebuild": "Rebuild Index",
    "verify": "Verify Files",
    "clear_artwork": "Clear Artwork Cache",
}


class LibraryHealthService:
    """Index-only health metrics with stable extension points for future checks."""

    def calculate(self, db: Session) -> dict:
        analytics = library_analytics.calculate(db)
        available = Song.availability_status == "available"
        missing_metadata_clause = missing_metadata_expression()
        row = db.execute(
            select(
                func.coalesce(func.sum(
                    case((Song.artwork_status == "missing", 1), else_=0)
                ), 0).label("missing_artwork"),
                func.coalesce(func.sum(
                    case((missing_metadata_clause, 1), else_=0)
                ), 0).label("missing_metadata"),
            ).where(available)
        ).one()
        last_updated = db.scalar(select(func.max(Song.last_indexed_at)))
        missing_files = db.scalar(
            select(func.count(Song.id)).where(Song.availability_status == "missing")
        ) or 0
        songs = int(analytics["songs"] or 0)
        possible = max(songs + missing_files, 1)
        penalty = (
            int(row.missing_artwork) * 0.30
            + int(row.missing_metadata) * 0.50
            + int(missing_files) * 0.20
        ) / possible
        score = max(0, min(100, round(100 * (1 - penalty))))

        checks = [
            {
                "id": "artwork",
                "label": "Artwork completeness",
                "count": int(row.missing_artwork),
                "status": "healthy" if not row.missing_artwork else "attention",
                "available": True,
            },
            {
                "id": "metadata",
                "label": "Metadata completeness",
                "count": int(row.missing_metadata),
                "status": "healthy" if not row.missing_metadata else "attention",
                "available": True,
            },
            {
                "id": "duplicates",
                "label": "Duplicate detection",
                "count": None,
                "status": "unavailable",
                "available": False,
            },
        ]
        return {
            "songs": songs,
            "albums": analytics["albums"],
            "artists": analytics["artists"],
            "storage_bytes": analytics["storage_bytes"],
            "missing_artwork": int(row.missing_artwork),
            "missing_metadata": int(row.missing_metadata),
            "duplicates": None,
            "health_score": score,
            "last_updated": last_updated,
            "checks": checks,
        }

    def create_action(self, db: Session, action: str) -> Task:
        if action not in HEALTH_ACTIONS:
            raise ValueError(f"Unsupported Library health action: {action}")
        if action == "verify":
            total = db.scalar(select(func.count(Song.id))) or 0
        elif action == "clear_artwork":
            total = db.scalar(select(func.count(Artwork.id))) or 0
        else:
            total = 1
        task = create_task(
            db,
            name=HEALTH_ACTIONS[action],
            spotify_url=f"library://maintenance/{action}",
            task_type=TaskType.LIBRARY_MAINTENANCE,
            total_items=max(int(total), 1),
        )
        task.operation_payload = json.dumps({"action": action})
        db.commit()
        return task


class LibraryMaintenanceWorker:
    def __init__(self, poll_seconds: float = 0.5):
        self.poll_seconds = poll_seconds
        self.settings = get_settings()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        db = SessionLocal()
        try:
            self._recover(db)
        finally:
            db.close()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="library-maintenance-worker"
        )
        self._thread.start()
        logger.info("Library maintenance worker started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Library maintenance worker stopped")

    def _recover(self, db: Session) -> None:
        db.execute(
            update(Task)
            .where(
                Task.task_type == TaskType.LIBRARY_MAINTENANCE.value,
                Task.status == TaskStatus.RUNNING.value,
            )
            .values(status=TaskStatus.QUEUED.value, current_item=None)
        )
        db.commit()

    def _run(self) -> None:
        while not self._stop.is_set():
            db = SessionLocal()
            try:
                task = db.scalar(
                    select(Task)
                    .where(
                        Task.task_type == TaskType.LIBRARY_MAINTENANCE.value,
                        Task.status == TaskStatus.QUEUED.value,
                    )
                    .order_by(Task.created_at, Task.id)
                    .limit(1)
                )
                if task:
                    self.process_task(db, task)
                    continue
            except Exception:
                logger.exception("Library maintenance worker recovered after failure")
                db.rollback()
                self._recover(db)
            finally:
                db.close()
            self._stop.wait(self.poll_seconds)

    def process_task(self, db: Session, task: Task) -> None:
        action = json.loads(task.operation_payload or "{}").get("action")
        if action == "verify":
            task.total_items = max(db.scalar(select(func.count(Song.id))) or 0, 1)
        elif action == "clear_artwork":
            task.total_items = max(db.scalar(select(func.count(Artwork.id))) or 0, 1)
        task.completed_items = 0
        task.failed_items = 0
        task.skipped_items = 0
        task.status = TaskStatus.RUNNING.value
        task.started_at = task.started_at or utcnow_naive()
        db.commit()
        try:
            if action == "refresh":
                task.current_item = "Scanning music folder"
                db.commit()
                scan_library(db, self.settings.music_path, force=False)
                task.completed_items = task.total_items
            elif action == "rebuild":
                task.current_item = "Rebuilding Library Index"
                db.commit()
                scan_library(db, self.settings.music_path, force=True)
                library_search.rebuild(db)
                db.commit()
                task.completed_items = task.total_items
            elif action == "verify":
                self._verify(db, task)
            elif action == "clear_artwork":
                self._clear_artwork(db, task)
            else:
                raise ValueError(f"Unknown maintenance action: {action}")
        except Exception:
            logger.exception("Library maintenance task {} failed", task.id)
            db.rollback()
            task = db.get(Task, task.id)
            task.failed_items = max(1, task.total_items - task.completed_items)
            task.status = TaskStatus.FAILED.value
        else:
            db.refresh(task)
            if task.status == TaskStatus.RUNNING.value:
                task.status = TaskStatus.COMPLETED.value
        task.current_item = None
        task.completed_at = utcnow_naive()
        db.commit()
        library_events.publish("library.health.updated", action=action, task_id=task.id)

    def _verify(self, db: Session, task: Task) -> None:
        song_ids = iter_primary_keys(db, Song)
        processed_any = False
        for song_id in song_ids:
            processed_any = True
            db.refresh(task)
            if task.status == TaskStatus.CANCELLED.value or self._stop.is_set():
                if self._stop.is_set() and task.status != TaskStatus.CANCELLED.value:
                    task.status = TaskStatus.QUEUED.value
                else:
                    task.skipped_items = task.total_items - task.completed_items - task.failed_items
                db.commit()
                return
            song = db.get(Song, song_id)
            task.current_item = song.filename
            try:
                index_file(db, song.path, force=False, commit=False)
                task.completed_items += 1
            except Exception:
                logger.exception("File verification failed for {}", song.path)
                db.rollback()
                task = db.get(Task, task.id)
                task.failed_items += 1
            db.commit()
        if not processed_any:
            task.completed_items = task.total_items

    def _clear_artwork(self, db: Session, task: Task) -> None:
        processed_any = False
        for artwork_id in iter_primary_keys(db, Artwork):
            processed_any = True
            db.refresh(task)
            if task.status == TaskStatus.CANCELLED.value or self._stop.is_set():
                if self._stop.is_set() and task.status != TaskStatus.CANCELLED.value:
                    task.status = TaskStatus.QUEUED.value
                else:
                    task.skipped_items = task.total_items - task.completed_items - task.failed_items
                db.commit()
                return
            artwork = db.get(Artwork, artwork_id)
            task.current_item = Path(artwork.cache_path).name
            try:
                Path(artwork.cache_path).unlink(missing_ok=True)
                db.execute(
                    update(Song)
                    .where(Song.artwork_id == artwork.id)
                    .values(artwork_id=None, artwork_status="missing", cover_url=None)
                )
                db.delete(artwork)
                task.completed_items += 1
            except Exception:
                logger.exception("Failed to clear artwork {}", artwork_id)
                db.rollback()
                task = db.get(Task, task.id)
                task.failed_items += 1
            db.commit()
        if not processed_any:
            task.completed_items = task.total_items


library_health = LibraryHealthService()
library_maintenance_worker = LibraryMaintenanceWorker()
