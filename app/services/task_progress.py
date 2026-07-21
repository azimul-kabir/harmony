"""Reusable serialization and lookup helpers for durable Harmony Tasks."""

import json
from typing import Any

from sqlalchemy.orm import Session

from app.database.models import Task
from app.domain.task import TaskType


def get_typed_task(db: Session, task_id: int, task_type: TaskType) -> Task | None:
    task = db.get(Task, task_id)
    if task is None or task.task_type != task_type.value:
        return None
    return task


def serialize_task_progress(task: Task) -> dict[str, Any]:
    """Serialize the stable progress contract shared by all task-backed APIs."""
    processed = task.completed_items + task.failed_items + task.skipped_items
    progress = round(processed / task.total_items * 100, 1) if task.total_items else 100
    recovery_metadata = None
    if task.recovery_metadata:
        try:
            recovery_metadata = json.loads(task.recovery_metadata)
        except (TypeError, ValueError):
            recovery_metadata = {"detail": "Recovery metadata is unavailable"}
    operation = {}
    if task.operation_payload:
        try:
            operation = json.loads(task.operation_payload)
        except (TypeError, ValueError):
            operation = {}
    return {
        "id": task.id,
        "job_id": task.id,
        "name": task.name,
        "type": task.task_type,
        "job_type": task.task_type,
        "status": task.status,
        "total": task.total_items,
        "total_items": task.total_items,
        "completed": task.completed_items,
        "successful_items": task.completed_items,
        "failed": task.failed_items,
        "failed_items": task.failed_items,
        "skipped": task.skipped_items,
        "skipped_items": task.skipped_items,
        "processed": processed,
        "processed_items": processed,
        "progress": progress,
        "progress_percentage": progress,
        "current": task.current_item,
        "current_item_description": task.current_item,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        "error_summary": task.error_summary,
        "error_code": task.error_code,
        "cancellation_requested_at": task.cancellation_requested_at,
        "initiated_by": task.initiated_by,
        "initiating_source_id": task.source_id,
        "resumable": task.resumable,
        "recovery_metadata": recovery_metadata,
        "operation": operation.get("action"),
        "counters": operation.get("counters", {}),
    }
