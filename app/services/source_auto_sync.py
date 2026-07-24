from __future__ import annotations

import threading
from datetime import UTC, timedelta

from sqlalchemy import select

from app.core.logging import logger
from app.core.time import utcnow_naive
from app.database.models import SyncSource, Task
from app.database.session import SessionLocal
from app.services.playlist_sync import sync_playlist


ACTIVE_STATUSES = ("queued", "running", "paused", "cancelling")


def next_sync_at(source: SyncSource):
    anchor = (
        source.auto_sync_last_attempt_at
        or source.last_synced_at
        or source.created_at
    )
    if anchor.tzinfo is not None:
        anchor = anchor.astimezone(UTC).replace(tzinfo=None)
    return anchor + timedelta(minutes=max(15, source.auto_sync_interval_minutes))


def due_sources(db, *, now=None):
    now = now or utcnow_naive()
    sources = db.scalars(
        select(SyncSource)
        .where(
            SyncSource.enabled.is_(True),
            SyncSource.auto_sync_enabled.is_(True),
        )
        .order_by(SyncSource.id)
    ).all()
    active_source_ids = set(
        db.scalars(
            select(Task.source_id).where(
                Task.source_id.is_not(None),
                Task.status.in_(ACTIVE_STATUSES),
            )
        ).all()
    )
    return [
        source
        for source in sources
        if source.id not in active_source_ids and next_sync_at(source) <= now
    ]


class SourceAutoSyncScheduler:
    def __init__(self, poll_seconds: float = 30):
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="source-auto-sync",
        )
        self._thread.start()
        logger.info("Source auto-sync scheduler started")

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        logger.info("Source auto-sync scheduler stopped")

    def _run(self):
        while not self._stop.is_set():
            db = SessionLocal()
            try:
                sources = due_sources(db)
                for source in sources:
                    if self._stop.is_set():
                        break
                    source.auto_sync_last_attempt_at = utcnow_naive()
                    db.commit()
                    logger.info("Starting automatic sync for source '{}'", source.name)
                    sync_playlist(db, source)
            except Exception:
                logger.exception("Source auto-sync scheduler iteration failed")
            finally:
                db.close()
            self._stop.wait(self.poll_seconds)


source_auto_sync_scheduler = SourceAutoSyncScheduler()
