"""Persist provider-neutral live download telemetry.

The ticker uses its own short-lived database sessions so a blocking downloader
cannot make an active job appear dead.  Byte metrics remain optional: callers
must report real measurements rather than estimates.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import threading

from sqlalchemy import update

from app.core.logging import logger
from app.database.models import DownloadJob
from app.database.session import SessionLocal
from app.domain.download import JobStatus


HEARTBEAT_INTERVAL_SECONDS = 5
STALE_HEARTBEAT_SECONDS = 30


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def update_telemetry(
    db,
    job: DownloadJob,
    *,
    stage: str | None = None,
    progress_percent: int | None = None,
    worker_name: str | None = None,
    bytes_downloaded: int | None = None,
    bytes_total: int | None = None,
    transfer_rate_bps: int | None = None,
    eta_seconds: int | None = None,
) -> None:
    if stage is not None:
        job.pipeline_stage = stage[:40]
    job.progress_percent = (
        max(0, min(100, int(progress_percent)))
        if progress_percent is not None
        else None
    )
    if worker_name is not None:
        job.worker_name = worker_name[:80]
    job.bytes_downloaded = bytes_downloaded
    job.bytes_total = bytes_total
    job.transfer_rate_bps = transfer_rate_bps
    job.eta_seconds = eta_seconds
    job.heartbeat_at = utcnow_naive()
    db.commit()


def _heartbeat(job_id: int) -> None:
    db = SessionLocal()
    try:
        db.execute(
            update(DownloadJob)
            .where(
                DownloadJob.id == job_id,
                DownloadJob.status == JobStatus.RUNNING.value,
            )
            .values(heartbeat_at=utcnow_naive())
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Unable to persist heartbeat for download #{}", job_id)
    finally:
        db.close()


@contextmanager
def heartbeat_ticker(job_id: int):
    stop = threading.Event()

    def tick() -> None:
        while not stop.wait(HEARTBEAT_INTERVAL_SECONDS):
            _heartbeat(job_id)

    thread = threading.Thread(
        target=tick,
        name=f"download-heartbeat-{job_id}",
        daemon=True,
    )
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=HEARTBEAT_INTERVAL_SECONDS)
