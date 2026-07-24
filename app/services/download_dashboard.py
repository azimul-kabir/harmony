"""Authoritative, privacy-safe read model for the Downloads operations center.

``download_jobs`` is deliberately the root of every query here.  A task is an
optional parent operation, not a download-history record (and tasks also cover
library maintenance work).
"""

from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, load_only

from app.database.models import DownloadJob
from app.domain.download import JobStatus
from app.services.download_bulk import capabilities


TERMINAL_STATUSES = ("completed", "failed", "skipped", "cancelled", "canceled")
QUEUE_LIMIT = 25
HISTORY_LIMIT = 250
DETAIL_EVENT_LIMIT = 3
COUNT_KEYS = ("running", "queued", "paused", "completed", "failed", "cancelled", "skipped")


def normalized_status(status: str | None) -> str:
    """Map persisted spelling variants to the Downloads UI's stable statuses."""
    value = (status or "").strip().lower()
    return "cancelled" if value == "canceled" else value


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC if value.tzinfo is None else value.tzinfo).isoformat().replace("+00:00", "Z")


def _job_columns():
    return load_only(DownloadJob.id, DownloadJob.task_id, DownloadJob.status, DownloadJob.title,
                     DownloadJob.artist, DownloadJob.album, DownloadJob.created_at,
                     DownloadJob.started_at, DownloadJob.completed_at, DownloadJob.updated_at,
                     DownloadJob.reason_code, DownloadJob.reason_message, DownloadJob.failure_stage,
                     DownloadJob.provider, DownloadJob.retryable, DownloadJob.technical_detail,
                     DownloadJob.error, DownloadJob.error_message, DownloadJob.source_provider,
                     DownloadJob.pipeline_stage, DownloadJob.progress_percent,
                     DownloadJob.heartbeat_at, DownloadJob.worker_name,
                     DownloadJob.bytes_downloaded, DownloadJob.bytes_total,
                     DownloadJob.transfer_rate_bps, DownloadJob.eta_seconds)


def _legacy_reason(job: DownloadJob, status: str) -> tuple[str | None, str | None]:
    """Read old rows conservatively; do not rewrite history based on guesses."""
    if job.reason_code or job.reason_message:
        return job.reason_code, job.reason_message
    text = (job.error_message or job.error or "").lower()
    if status == "failed" and "already exists" in text:
        return "already_exists", "The destination file already existed."
    if status == "failed":
        return "legacy_failure", "This older download failed; no structured reason was recorded."
    return None, None


def _safe_detail(value: str | None) -> str | None:
    if not value:
        return None
    # Diagnostics are intentionally type/category-only in current workers; defend
    # legacy values from tokens, URLs and unrestricted paths as well.
    import re
    value = re.sub(r"(?i)(token|password|cookie|authorization)=?[^\s&]+", r"\1=[redacted]", value)
    value = re.sub(r"https?://\S+", "[remote URL redacted]", value)
    value = re.sub(r"(?:[A-Za-z]:)?/[^\s]+", "[path redacted]", value)
    return value[:240]


def serialize_outcome(job: DownloadJob) -> dict:
    status = normalized_status(job.status)
    # These columns describe a *terminal* outcome.  In particular, do not let a
    # partially populated row make a queued/running job look as though it failed.
    # This also makes the serializer safe for jobs created before a worker has
    # recorded any outcome fields.
    if status not in TERMINAL_STATUSES:
        return {"status": status, "reason_code": None, "reason_message": None,
                "failure_stage": None, "provider": None, "retryable": False,
                "finished_at": None, "technical_detail": None}
    code, message = _legacy_reason(job, status)
    return {"status": status, "reason_code": code, "reason_message": message,
            "failure_stage": job.failure_stage, "provider": job.provider,
            "retryable": bool(job.retryable) if status == "failed" else False,
            "finished_at": _timestamp(job.completed_at),
            "technical_detail": _safe_detail(job.technical_detail)}


def _history_job(job: DownloadJob) -> dict:
    outcome = serialize_outcome(job)
    return {"id": job.id, "task_id": job.task_id, "title": job.title,
            "artist": job.artist, "album": job.album, "created_at": _timestamp(job.created_at),
            "started_at": _timestamp(job.started_at), "completed_at": _timestamp(job.completed_at),
            "updated_at": _timestamp(job.updated_at), "error_category": outcome["reason_message"],
            **outcome, "capabilities": capabilities(job)}


def _history_order():
    return (DownloadJob.updated_at.desc(), DownloadJob.completed_at.desc(),
            DownloadJob.created_at.desc(), DownloadJob.id.desc())


def download_counts(db: Session) -> dict[str, int]:
    """Return a zero-filled count for every normalized download status."""
    rows = db.execute(select(DownloadJob.status, func.count(DownloadJob.id)).group_by(DownloadJob.status)).all()
    counts = dict.fromkeys(COUNT_KEYS, 0)
    for status, count in rows:
        key = normalized_status(status)
        if key in counts:
            counts[key] += int(count)
    return counts


def download_history(db: Session, *, page: int = 1, page_size: int = HISTORY_LIMIT,
                     status: str | None = None, search: str | None = None) -> dict:
    """Fetch persisted track history without requiring a parent task or worker."""
    page = max(1, page)
    page_size = max(1, min(page_size, HISTORY_LIMIT))
    query = select(DownloadJob).options(_job_columns())
    normalized = normalized_status(status)
    if normalized and normalized != "all":
        aliases = ("cancelled", "canceled") if normalized == "cancelled" else (normalized,)
        query = query.where(DownloadJob.status.in_(aliases))
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.where(or_(DownloadJob.title.ilike(term), DownloadJob.artist.ilike(term), DownloadJob.album.ilike(term)))
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    jobs = db.scalars(query.order_by(*_history_order()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_history_job(job) for job in jobs], "total": total, "page": page, "page_size": page_size}


def _duration_seconds(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds()))


def _stage(status: str) -> str:
    return {"queued": "Queued", "running": "Downloading", "paused": "Paused", "completed": "Completed",
            "failed": "Failed", "cancelled": "Cancelled", "skipped": "Skipped"}.get(normalized_status(status), "Unknown")


def serialize_telemetry(job: DownloadJob) -> dict:
    return {
        "stage": job.pipeline_stage,
        "progress": job.progress_percent,
        "heartbeat_at": _timestamp(job.heartbeat_at),
        "worker": job.worker_name,
        "bytes_downloaded": job.bytes_downloaded,
        "bytes_total": job.bytes_total,
        "transfer_rate_bps": job.transfer_rate_bps,
        "eta_seconds": job.eta_seconds,
    }


def download_details(job: DownloadJob) -> dict:
    events: list[tuple[datetime, int, dict]] = []
    if job.created_at is not None:
        events.append((job.created_at, 0, {"key": "queued", "label": "Queued", "occurred_at": _timestamp(job.created_at), "status": "completed", "description": None}))
    if job.started_at is not None:
        events.append((job.started_at, 1, {"key": "started", "label": "Started", "occurred_at": _timestamp(job.started_at), "status": "completed", "description": None}))
    status = normalized_status(job.status)
    terminal = {"completed": ("completed", "Completed"), "failed": ("failed", "Failed"), "cancelled": ("cancelled", "Cancelled"), "skipped": ("skipped", "Skipped")}.get(status)
    if terminal is not None and job.completed_at is not None:
        key, label = terminal
        events.append((job.completed_at, 2, {"key": key, "label": label, "occurred_at": _timestamp(job.completed_at), "status": "completed", "description": None}))
    events.sort(key=lambda item: (item[0], item[1]))
    outcome = serialize_outcome(job)
    return {"id": job.id, "task_id": job.task_id, "title": job.title, "artist": job.artist, "album": job.album,
            "source": "YouTube Music" if job.source_provider == "youtube_music" else "Spotify", "status": status,
            **serialize_telemetry(job),
            "stage": job.pipeline_stage or _stage(status),
            "progress": 100 if status == "completed" else job.progress_percent, "created_at": _timestamp(job.created_at),
            "started_at": _timestamp(job.started_at), "finished_at": _timestamp(job.completed_at),
            "queue_wait_seconds": _duration_seconds(job.created_at, job.started_at),
            "run_duration_seconds": _duration_seconds(job.started_at, job.completed_at), "retry_count": 0,
            "can_cancel": status in ("queued", "running"), "can_retry": status == "failed" and bool(job.retryable),
            **outcome,
            "events": [event for _, _, event in events[:DETAIL_EVENT_LIMIT]]}


def get_download_snapshot(db: Session, *, queue_limit: int = QUEUE_LIMIT,
                          history_limit: int = HISTORY_LIMIT) -> dict:
    """Return DB-backed counters, live queue, and first bounded history page."""
    queue_limit = max(1, min(queue_limit, QUEUE_LIMIT))
    history = download_history(db, page_size=history_limit)
    def queue(status: str):
        return db.scalars(select(DownloadJob).options(_job_columns()).where(DownloadJob.status == status)
                          .order_by(DownloadJob.created_at.asc(), DownloadJob.id.asc()).limit(queue_limit)).all()
    active, queued, paused = queue("running"), queue("queued"), queue("paused")
    return {"event_type": "snapshot", "counts": download_counts(db),
            "active": [{"id": j.id, "task_id": j.task_id, "title": j.title, "artist": j.artist, "status": normalized_status(j.status), **serialize_telemetry(j), "worker_slot": j.worker_name, "started_at": _timestamp(j.started_at)} for j in active],
            "queued": [{"id": j.id, "task_id": j.task_id, "title": j.title, "artist": j.artist, "position": i, "status": normalized_status(j.status), "created_at": _timestamp(j.created_at)} for i, j in enumerate(queued, 1)],
            "paused": [{"id": j.id, "task_id": j.task_id, "title": j.title, "artist": j.artist, "position": i, "status": normalized_status(j.status), "created_at": _timestamp(j.created_at)} for i, j in enumerate(paused, 1)],
            "jobs": history["items"], "history": history}


def download_diagnostics(db: Session) -> dict[str, int | dict[str, int]]:
    """Aggregate-only diagnostic for production troubleshooting; never exposes job data."""
    snapshot = get_download_snapshot(db, history_limit=1)
    return {"download_jobs_total": int(sum(snapshot["counts"].values())), "counts": snapshot["counts"],
            "recent_history_result_count": int(snapshot["history"]["total"]),
            "live_queue_result_count": len(snapshot["active"]) + len(snapshot["queued"]) + len(snapshot["paused"]),
            "active_worker_job_count": len(snapshot["active"]), "api_serializer_result_count": len(snapshot["jobs"])}
