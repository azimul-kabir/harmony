"""Reusable serialization and lookup helpers for durable Harmony Tasks."""

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
    return {
        "id": task.id,
        "name": task.name,
        "type": task.task_type,
        "status": task.status,
        "total": task.total_items,
        "completed": task.completed_items,
        "failed": task.failed_items,
        "skipped": task.skipped_items,
        "processed": processed,
        "progress": round(processed / task.total_items * 100, 1) if task.total_items else 100,
        "current": task.current_item,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
    }
