from datetime import UTC, datetime
from sqlalchemy.orm import Session
from app.database.models import Task, SyncSource
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
    source_id: int | None = None,
) -> Task:
    task = Task(
        name=name,
        spotify_url=spotify_url,
        source_id=source_id,
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

def _complete_task(
    db: Session,
    task: Task,
) -> None:
    task.status = TaskStatus.COMPLETED.value
    task.completed_at = datetime.now(UTC)
    task.current_item = None
    db.commit()
    db.refresh(task)

def _fail_task(
    db: Session,
    task: Task,
) -> None:
    task.status = TaskStatus.FAILED.value
    task.completed_at = datetime.now(UTC)
    task.current_item = None
    db.commit()
    db.refresh(task)

def set_current_item(
    db: Session,
    task: Task,
    item: str | None,
) -> None:
    task.current_item = item
    db.commit()
    db.refresh(task)

def increment_completed(
    db: Session,
    task: Task,
) -> None:
    task.completed_items += 1
    db.commit()
    db.refresh(task)
    _finish_if_complete(
        db=db,
        task=task,
    )

def increment_failed(
    db: Session,
    task: Task,
) -> None:
    task.failed_items += 1
    db.commit()
    db.refresh(task)
    _finish_if_complete(
        db=db,
        task=task,
    )

def increment_skipped(
    db: Session,
    task: Task,
) -> None:
    task.skipped_items += 1
    db.commit()
    db.refresh(task)
    _finish_if_complete(
        db=db,
        task=task,
    )

def _finish_if_complete(
    db: Session,
    task: Task,
) -> None:
    finished = (
        task.completed_items
        + task.failed_items
        + task.skipped_items
    )
    if finished < task.total_items:
        return

    task.current_item = None
    task.completed_at = datetime.now(UTC)

    if task.failed_items > 0:
        task.status = TaskStatus.FAILED.value
    else:
        task.status = TaskStatus.COMPLETED.value
        
        # UPDATE SOURCE LAST SYNC TIME
        if task.source_id:
            source = db.get(SyncSource, task.source_id)
            if source:
                source.last_synced_at = datetime.now(UTC)

    db.commit()
    db.refresh(task)

def pause_task(
    db: Session,
    task: Task,
) -> None:
    if task.status in (TaskStatus.QUEUED.value, TaskStatus.RUNNING.value):
        task.status = TaskStatus.PAUSED.value
        db.commit()
        db.refresh(task)

def resume_task(
    db: Session,
    task: Task,
) -> None:
    if task.status == TaskStatus.PAUSED.value:
        task.status = TaskStatus.QUEUED.value
        db.commit()
        db.refresh(task)

def cancel_task(
    db: Session,
    task: Task,
) -> None:
    if task.status not in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value):
        task.status = TaskStatus.CANCELLED.value
        task.completed_at = datetime.now(UTC)
        task.current_item = None
        db.commit()
        db.refresh(task)
