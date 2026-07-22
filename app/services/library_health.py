from __future__ import annotations

import json
import asyncio
import itertools
from pathlib import Path
import threading

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import logger
from app.core.time import utcnow_naive
from app.database.models import Artwork, MetadataDiscovery, MetadataIssue, Song, Task
from app.database.session import SessionLocal
from app.database.pagination import iter_primary_keys
from app.domain.task import TaskStatus, TaskType
from app.services.library_analytics import library_analytics
from app.services.library_events import library_events
from app.services.library_scanner import index_file, scan_library
from app.services.library_search import library_search
from app.services.library_predicates import missing_metadata_expression
from app.services.task_service import create_task, record_item_failure
from app.services.metadata_health import metadata_health
from app.services.metadata_discovery import metadata_discovery_service


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
            operation_payload=json.dumps({"action": action}),
            resource_key="library-files" if action in {"refresh", "rebuild", "verify", "clear_artwork"} else None,
        )
        return task

    def create_metadata_analysis(self, db: Session) -> Task:
        # Missing rows are counted as skipped so total = successful + failed + skipped.
        total = db.scalar(select(func.count(Song.id))) or 0
        return create_task(db, name="Metadata Health Analysis", spotify_url="library://metadata-health/analyze",
            task_type=TaskType.LIBRARY_MAINTENANCE, total_items=max(int(total), 1),
            operation_payload=json.dumps({"action":"metadata_analysis"}), resource_key="library-metadata-health")


class LibraryMaintenanceWorker:
    def __init__(self, poll_seconds: float = 0.5):
        self.poll_seconds = poll_seconds
        self.settings = get_settings()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

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
                Task.status.in_((TaskStatus.RUNNING.value, TaskStatus.CANCELLING.value)),
            )
            .values(status=TaskStatus.INTERRUPTED.value, current_item=None, completed_at=utcnow_naive())
        )
        db.commit()

    def _run(self) -> None:
        self._loop=asyncio.new_event_loop()
        try:
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
        finally:
            self._loop.close();self._loop=None

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
            elif action == "metadata_analysis":
                self._metadata_analysis(db, task)
            elif action == "metadata_discovery":
                self._metadata_discovery(db, task)
            elif action in {"metadata_application", "metadata_rollback"}:
                from app.services.metadata_intelligence import metadata_application_service
                metadata_application_service.process_task(db, task)
            else:
                raise ValueError(f"Unknown maintenance action: {action}")
        except Exception:
            logger.exception("Library maintenance task {} failed", task.id)
            db.rollback()
            task = db.get(Task, task.id)
            task.failed_items = max(1, task.total_items - task.completed_items)
            task.status = TaskStatus.FAILED.value
            if action in {"metadata_application", "metadata_rollback"}:
                from app.database.models import MetadataApplicationBatch, MetadataApplicationLock
                payload = json.loads(task.operation_payload or "{}")
                batch_id = payload.get("batch_id")
                if isinstance(batch_id, int):
                    batch = db.get(MetadataApplicationBatch, batch_id)
                    if batch is not None:
                        batch.status = "failed"
                        batch.completed_at = utcnow_naive()
                db.execute(delete(MetadataApplicationLock).where(MetadataApplicationLock.task_id == task.id))
        else:
            if task.status == TaskStatus.RUNNING.value:
                task.status = TaskStatus.COMPLETED_WITH_ERRORS.value if task.failed_items else TaskStatus.COMPLETED.value
        task.current_item = None
        if task.status != TaskStatus.QUEUED.value:
            task.completed_at = utcnow_naive()
        db.commit()
        library_events.publish("library.health.updated", action=action, task_id=task.id)

    def _metadata_discovery(self, db: Session, task: Task) -> None:
        payload=json.loads(task.operation_payload or "{}")
        song_ids=payload.get("song_ids") if isinstance(payload.get("song_ids"),list) else []
        counters=payload.setdefault("counters",{})
        provider=payload.get("provider","musicbrainz")
        discoveries={int(item.entity_id):item for item in db.scalars(select(MetadataDiscovery).where(
            MetadataDiscovery.job_id==task.id,MetadataDiscovery.entity_type=="song")).all() if item.entity_id.isdigit()}
        try:
            chunk_size=max(1,self.settings.metadata_discovery_chunk_size)
            chunks=(song_ids[start:start+chunk_size] for start in range(0,len(song_ids),chunk_size))
            for song_id in itertools.chain.from_iterable(chunks):
                db.refresh(task)
                if task.status in (TaskStatus.CANCELLED.value,TaskStatus.CANCELLING.value) or self._stop.is_set():
                    task.status=TaskStatus.INTERRUPTED.value if self._stop.is_set() else TaskStatus.CANCELLED.value
                    task.skipped_items=max(0,task.total_items-task.completed_items-task.failed_items)
                    for item in discoveries.values():
                        if item.status in ("queued","running"): item.status="cancelled";item.completed_at=utcnow_naive()
                    db.commit();return
                discovery=discoveries.get(song_id);song=db.get(Song,song_id)
                if song is None:
                    task.skipped_items+=1
                    record_item_failure(db,task,str(song_id),"DISCOVERY_SONG_NOT_FOUND","Selected Song no longer exists")
                    if discovery: discovery.status="failed";discovery.completed_at=utcnow_naive();discovery.error_metadata='[{"code":"entity_not_found"}]'
                    db.commit();continue
                task.current_item=f"Song {song_id}"
                cancel_event=asyncio.Event()
                progress_state={"candidates":0,"duplicates":0,"failures":0}
                def progress(processed,total,candidate_count,duplicate_count,failure_count):
                    db.expire(task);db.refresh(task)
                    counters["search_variants_total"]=counters.get("search_variants_total",0)+(total if processed==1 else 0)
                    counters["search_variants_processed"]=counters.get("search_variants_processed",0)+1
                    counters["candidates_found"]=counters.get("candidates_found",0)+max(0,candidate_count-progress_state["candidates"])
                    counters["candidates_deduplicated"]=counters.get("candidates_deduplicated",0)+max(0,duplicate_count-progress_state["duplicates"])
                    counters["provider_failures"]=counters.get("provider_failures",0)+max(0,failure_count-progress_state["failures"])
                    progress_state.update(candidates=candidate_count,duplicates=duplicate_count,failures=failure_count)
                    task.operation_payload=json.dumps(payload,separators=(",",":"));db.commit()
                    if task.status in (TaskStatus.CANCELLING.value,TaskStatus.CANCELLED.value): cancel_event.set()
                try:
                    if self._loop is None: raise RuntimeError("Metadata discovery event loop is unavailable")
                    item=self._loop.run_until_complete(metadata_discovery_service.discover_song(db,song_id,provider_name=provider,
                        cancel_event=cancel_event,job_id=task.id,discovery_id=discovery.id if discovery else None,progress=progress))
                    if item.status=="cancelled":
                        task.status=TaskStatus.CANCELLED.value;task.skipped_items=max(0,task.total_items-task.completed_items-task.failed_items);db.commit();return
                    viable=sum(1 for result in item.results if result.viable);rejected=sum(1 for result in item.results if result.hard_rejection)
                    counters["viable_candidates"]=counters.get("viable_candidates",0)+viable
                    counters["rejected_candidates"]=counters.get("rejected_candidates",0)+rejected
                    if item.ambiguous: counters["ambiguous"]=counters.get("ambiguous",0)+1
                    elif viable: counters["matched"]=counters.get("matched",0)+1
                    else: counters["unmatched"]=counters.get("unmatched",0)+1
                    task.completed_items+=1
                except Exception:
                    db.rollback();task=db.get(Task,task.id);payload=json.loads(task.operation_payload or "{}");counters=payload.setdefault("counters",{})
                    task.failed_items+=1;record_item_failure(db,task,str(song_id),"METADATA_DISCOVERY_FAILED","Metadata candidates could not be discovered")
                    failed=db.get(MetadataDiscovery,discovery.id) if discovery else None
                    if failed: failed.status="failed";failed.completed_at=utcnow_naive();failed.error_metadata='[{"code":"discovery_failed"}]'
                task.operation_payload=json.dumps(payload,separators=(",",":"));db.commit()
        finally:
            metadata_discovery_service.release_locks(db,task.id);db.commit()
        if counters.get("provider_failures") and task.status==TaskStatus.RUNNING.value:
            task.status=TaskStatus.COMPLETED_WITH_ERRORS.value

    def _verify(self, db: Session, task: Task) -> None:
        song_ids = iter_primary_keys(db, Song)
        processed_any = False
        for song_id in song_ids:
            processed_any = True
            db.refresh(task)
            if task.status in (TaskStatus.CANCELLED.value, TaskStatus.CANCELLING.value) or self._stop.is_set():
                if self._stop.is_set() and task.status not in (TaskStatus.CANCELLED.value, TaskStatus.CANCELLING.value):
                    task.status = TaskStatus.INTERRUPTED.value
                    task.recovery_metadata = '{"reason":"worker_shutdown"}'
                else:
                    task.status = TaskStatus.CANCELLED.value
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
                record_item_failure(db, task, song.filename, "FILE_VERIFICATION_FAILED", "File could not be verified")
            db.commit()
        if not processed_any:
            task.completed_items = task.total_items

    def _clear_artwork(self, db: Session, task: Task) -> None:
        processed_any = False
        for artwork_id in iter_primary_keys(db, Artwork):
            processed_any = True
            db.refresh(task)
            if task.status in (TaskStatus.CANCELLED.value, TaskStatus.CANCELLING.value) or self._stop.is_set():
                if self._stop.is_set() and task.status not in (TaskStatus.CANCELLED.value, TaskStatus.CANCELLING.value):
                    task.status = TaskStatus.INTERRUPTED.value
                    task.recovery_metadata = '{"reason":"worker_shutdown"}'
                else:
                    task.status = TaskStatus.CANCELLED.value
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
                record_item_failure(db, task, str(artwork_id), "ARTWORK_CACHE_FAILED", "Artwork cache entry could not be cleared")
            db.commit()
        if not processed_any:
            task.completed_items = task.total_items

    def _metadata_analysis(self, db: Session, task: Task) -> None:
        song_ids = list(iter_primary_keys(db, Song))
        if not song_ids:
            task.skipped_items = task.total_items
        for start in range(0, len(song_ids), 500):
            db.refresh(task)
            if task.status in (TaskStatus.CANCELLED.value, TaskStatus.CANCELLING.value) or self._stop.is_set():
                task.status = TaskStatus.CANCELLED.value
                task.skipped_items = max(0, task.total_items - task.completed_items - task.failed_items)
                db.commit(); return
            batch_ids = song_ids[start:start + 500]
            batch = list(db.scalars(select(Song).where(Song.id.in_(batch_ids))).all())
            findings = []
            analyzed_ids = []
            for song in batch:
                if song.availability_status != "available":
                    task.skipped_items += 1
                    continue
                try:
                    task.current_item = song.filename
                    findings.extend(metadata_health.detect_song(song))
                    analyzed_ids.append(song.id)
                    task.completed_items += 1
                except Exception:
                    logger.exception("Metadata analysis failed for song {}", song.id)
                    task.failed_items += 1
                    record_item_failure(db, task, str(song.id), "METADATA_ANALYSIS_FAILED", "Indexed metadata could not be analyzed")
            metadata_health.reconcile(db, findings, scope=("song", analyzed_ids), job_id=task.id)
            db.commit()
        # Projection rules run from one batched indexed query after song rules.
        db.refresh(task)
        if task.status in (TaskStatus.CANCELLED.value, TaskStatus.CANCELLING.value) or self._stop.is_set():
            task.status = TaskStatus.CANCELLED.value
            task.skipped_items = max(0, task.total_items - task.completed_items - task.failed_items)
            db.commit()
            return
        available_songs = list(db.scalars(select(Song).where(Song.availability_status == "available")).all())
        metadata_health._analyze_projections(db, available_songs, task.id)
        # A successful complete pass reconciles findings that disappeared at
        # every scope. During a partial pass, preserve stale issues because the
        # failed entity may still trigger them.
        if not task.failed_items:
            now = utcnow_naive()
            db.execute(
                update(MetadataIssue)
                .where(
                    MetadataIssue.status == "open",
                    (MetadataIssue.detection_job_id.is_(None) | (MetadataIssue.detection_job_id != task.id)),
                )
                .values(status="resolved", resolved_at=now)
            )
        db.commit()


library_health = LibraryHealthService()
library_maintenance_worker = LibraryMaintenanceWorker()
