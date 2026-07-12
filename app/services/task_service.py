from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.database.models import Task
from app.domain.task import (
    TaskStatus,
    TaskType,
)


def create_task(
    db: Session,
    *,
    name: str,
    spotify_url: str,
    task_type: TaskType,
    total_items: int,
) -> Task:
    task = Task(
        name=name,
        spotify_url=spotify_url,
        task_type=task_type.value,
        status=TaskStatus.QUEUED.value,
        total_items=total_items,
        completed_items=0,
        skipped_items=0,
        failed_items=0,
        current_item=None,
    )

    db.add(task)
    db.commit()
    db.refresh(task)

    return task


def start_task(
    db: Session,
    task: Task,
) -> None:
    task.status = TaskStatus.RUNNING.value
    task.started_at = datetime.now(UTC)

    db.commit()
    db.refresh(task)


def complete_task(
    db: Session,
    task: Task,
) -> None:
    task.status = TaskStatus.COMPLETED.value
    task.completed_at = datetime.now(UTC)
    task.current_item = None

    db.commit()
    db.refresh(task)


def fail_task(
    db: Session,
    task: Task,
) -> None:
    task.status = TaskStatus.FAILED.value
    task.completed_at = datetime.now(UTC)
    task.current_item = None

    db.commit()
    db.refresh(task)


def update_progress(
    db: Session,
    task: Task,
    *,
    current_item: str | None = None,
    completed: int | None = None,
    skipped: int | None = None,
    failed: int | None = None,
) -> None:
    if current_item is not None:
        task.current_item = current_item

    if completed is not None:
        task.completed_items = completed

    if skipped is not None:
        task.skipped_items = skipped

    if failed is not None:
        task.failed_items = failed

    db.commit()
    db.refresh(task)