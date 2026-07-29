"""Durable bulk Loved-status jobs using only Navidrome's Subsonic API."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.time import utcnow_naive
from app.database.models import Task
from app.database.session import SessionLocal
from app.services.navidrome import NavidromeClient, NavidromeError

TASK_TYPE = "navidrome_love"
TERMINAL = {"completed", "completed_with_errors", "failed", "cancelled"}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


def public_job(task: Task) -> dict:
    data = json.loads(task.operation_payload or "{}")
    return {
        "job_id": task.id,
        "status": "partially_completed"
        if task.status == "completed_with_errors"
        else task.status,
        "playlist_id": data.get("playlist_id"),
        "playlist_name": data.get("playlist_name"),
        "operation": data.get("operation"),
        "total_tracks": task.total_items,
        "processed_tracks": task.completed_items + task.failed_items,
        "successful_tracks": task.completed_items,
        "failed_tracks": task.failed_items,
        "current_batch": data.get("current_batch", 0),
        "total_batches": data.get("total_batches", 0),
        "started_at": _iso(task.started_at),
        "completed_at": _iso(task.completed_at),
        "error_category": task.error_code,
        "safe_error_message": task.error_summary,
    }


def create_job(playlist_id: str, playlist_name: str, operation: str) -> Task:
    db = SessionLocal()
    try:
        task = Task(
            name=f"{operation.title()} Navidrome playlist",
            spotify_url="",
            task_type=TASK_TYPE,
            resource_key=f"navidrome:{playlist_id}:{operation}",
            operation_payload=json.dumps(
                {
                    "playlist_id": playlist_id,
                    "playlist_name": playlist_name,
                    "operation": operation,
                    "current_batch": 0,
                    "total_batches": 0,
                }
            ),
        )
        db.add(task)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ValueError(
                "This operation is already active for that playlist."
            ) from exc
        db.refresh(task)
        return task
    finally:
        db.close()


async def run_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        task = db.get(Task, job_id)
        if not task or task.status != "queued":
            return
        task.status = "running"
        task.started_at = utcnow_naive()
        db.commit()
        data = json.loads(task.operation_payload or "{}")
        client = NavidromeClient()
        try:
            playlist = await client.get_playlist(data["playlist_id"])
            entries = NavidromeClient._as_list(playlist.get("entry"))
            ids = [entry.get("id") for entry in entries]
            if any(not isinstance(item, str) or not item.strip() for item in ids):
                raise NavidromeError(
                    "Navidrome returned invalid playlist tracks.",
                    code="invalid_playlist_response",
                )
            data["playlist_name"] = str(playlist.get("name") or data["playlist_name"])
            task.total_items = len(ids)
            data["total_batches"] = (
                len(ids) + get_settings().navidrome_love_batch_size - 1
            ) // get_settings().navidrome_love_batch_size
            task.operation_payload = json.dumps(data)
            db.commit()

            def progress(batch, total_batches, processed, total):
                data["current_batch"] = batch
                data["total_batches"] = total_batches
                task.completed_items = processed
                task.total_items = total
                task.current_item = f"Batch {batch} of {total_batches}"
                task.operation_payload = json.dumps(data)
                db.commit()

            method = (
                client.star_song_ids
                if data["operation"] == "love"
                else client.unstar_song_ids
            )
            await method(ids, progress=progress)
            task.status = "completed"
            task.completed_at = utcnow_naive()
            db.commit()
        except NavidromeError as exc:
            processed = task.completed_items
            task.failed_items = max(0, task.total_items - processed)
            task.status = "completed_with_errors" if processed else "failed"
            task.error_code = (
                "partial_batch_failure"
                if processed
                else (
                    "playlist_not_found"
                    if exc.api_code == 70
                    else exc.code.replace("navidrome_", "")
                )
            )
            task.error_summary = (
                "Some batches completed before Navidrome stopped the operation."
                if processed
                else str(exc)
            )
            task.completed_at = utcnow_naive()
            db.commit()
        except Exception:
            task.status = "completed_with_errors" if task.completed_items else "failed"
            task.error_code = (
                "partial_batch_failure" if task.completed_items else "unexpected_error"
            )
            task.error_summary = (
                "Some batches completed before an unexpected error."
                if task.completed_items
                else "The Navidrome operation could not be completed."
            )
            task.completed_at = utcnow_naive()
            db.commit()
    finally:
        db.close()
