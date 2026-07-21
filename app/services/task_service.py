from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.database.models import MetadataDiscovery, MetadataDiscoveryLock, Task, TaskItemFailure, SyncSource
from sqlalchemy import select, delete, update
from app.domain.task import (
    TaskStatus,
    TaskType,
)
from app.core.time import utcnow_naive

def create_task(
    db: Session,
    *,
    name: str,
    spotify_url: str,
    task_type: TaskType,
    total_items: int,
    source_id: int | None = None,
    operation_payload: str | None = None,
    commit: bool = True,
    resource_key: str | None = None,
    initiated_by: str | None = None,
    resumable: bool = False,
) -> Task:
    # A resource key is a durable cross-worker mutex.  It deliberately covers
    # queued jobs too: file operations must never race while waiting to start.
    if resource_key:
        conflict = db.scalar(select(Task.id).where(Task.resource_key == resource_key,
            Task.status.in_((TaskStatus.QUEUED.value, TaskStatus.RUNNING.value, TaskStatus.CANCELLING.value))))
        if conflict:
            raise ValueError(f"CONFLICTING_JOB: job {conflict} already owns this resource")
    task = Task(
        name=name,
        spotify_url=spotify_url,
        source_id=source_id,
        task_type=task_type.value,
        status=TaskStatus.QUEUED.value,
        resource_key=resource_key,
        initiated_by=initiated_by,
        resumable=resumable,
        total_items=total_items,
        completed_items=0,
        skipped_items=0,
        failed_items=0,
        current_item=None,
        operation_payload=operation_payload,
    )
    db.add(task)
    if not commit:
        try:
            db.flush()
        except IntegrityError as error:
            db.rollback()
            if resource_key:
                raise ValueError("CONFLICTING_JOB: resource is already reserved") from error
            raise
        return task
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if resource_key:
            raise ValueError("CONFLICTING_JOB: resource is already reserved") from error
        raise
    db.refresh(task)
    return task

def start_task(
    db: Session,
    task: Task,
) -> None:
    task.status = TaskStatus.RUNNING.value
    task.started_at = utcnow_naive()
    db.commit()
    db.refresh(task)

def _complete_task(
    db: Session,
    task: Task,
) -> None:
    task.status = TaskStatus.COMPLETED.value
    task.completed_at = utcnow_naive()
    task.current_item = None
    db.commit()
    db.refresh(task)

def _fail_task(
    db: Session,
    task: Task,
) -> None:
    task.status = TaskStatus.FAILED.value
    task.completed_at = utcnow_naive()
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
    task.completed_at = utcnow_naive()

    if task.failed_items > 0:
        task.status = TaskStatus.FAILED.value
    else:
        task.status = TaskStatus.COMPLETED.value
        
        # UPDATE SOURCE LAST SYNC TIME
        if task.source_id:
            source = db.get(SyncSource, task.source_id)
            if source:
                source.last_synced_at = utcnow_naive()

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
    if task.status not in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value, TaskStatus.COMPLETED_WITH_ERRORS.value, TaskStatus.INTERRUPTED.value):
        task.cancellation_requested_at = utcnow_naive()
        # Queued work can be stopped immediately; workers acknowledge running work
        # between items so filesystem/database reconciliation remains atomic.
        task.status = TaskStatus.CANCELLED.value if task.status == TaskStatus.QUEUED.value else TaskStatus.CANCELLING.value
        if task.status == TaskStatus.CANCELLED.value:
            task.completed_at = utcnow_naive()
            task.current_item = None
            db.execute(delete(MetadataDiscoveryLock).where(MetadataDiscoveryLock.task_id == task.id))
            db.execute(update(MetadataDiscovery).where(MetadataDiscovery.job_id==task.id,
                MetadataDiscovery.status.in_(("queued","running"))).values(status="cancelled",completed_at=utcnow_naive()))
        db.commit()
        db.refresh(task)


def record_item_failure(db: Session, task: Task, item: str, code: str, message: str) -> None:
    """Persist bounded, non-secret error details (newest 100 per job)."""
    db.add(TaskItemFailure(task_id=task.id, item_description=item[:500], error_code=code[:80], message=message[:500]))
    db.flush()
    old = db.scalars(select(TaskItemFailure.id).where(TaskItemFailure.task_id == task.id).order_by(TaskItemFailure.id.desc()).offset(100)).all()
    if old:
        db.execute(delete(TaskItemFailure).where(TaskItemFailure.id.in_(old)))
    task.error_code, task.error_summary = code[:80], message[:500]


def cleanup_library_jobs(db: Session, *, retain: int = 200) -> int:
    """Delete the oldest terminal Library jobs beyond a bounded history."""
    retain = max(0, retain)
    terminal = (
        TaskStatus.CANCELLED.value,
        TaskStatus.COMPLETED.value,
        TaskStatus.COMPLETED_WITH_ERRORS.value,
        TaskStatus.FAILED.value,
        TaskStatus.INTERRUPTED.value,
    )
    old_ids = db.scalars(
        select(Task.id)
        .where(
            Task.task_type.in_((TaskType.LIBRARY_BULK.value, TaskType.LIBRARY_MAINTENANCE.value)),
            Task.status.in_(terminal),
        )
        .order_by(Task.created_at.desc(), Task.id.desc())
        .offset(retain)
    ).all()
    if not old_ids:
        return 0
    # ORM deletion applies the existing cascades for item records and failures.
    for task in db.scalars(select(Task).where(Task.id.in_(old_ids))).all():
        db.delete(task)
    db.commit()
    return len(old_ids)


def recover_library_jobs(db: Session) -> int:
    """Mark abandoned non-resumable library work interrupted at process startup."""
    jobs = db.scalars(select(Task).where(Task.task_type.in_((TaskType.LIBRARY_BULK.value, TaskType.LIBRARY_MAINTENANCE.value)), Task.status.in_((TaskStatus.RUNNING.value, TaskStatus.CANCELLING.value)))).all()
    for task in jobs:
        task.status = TaskStatus.QUEUED.value if task.resumable else TaskStatus.INTERRUPTED.value
        task.current_item = None
        task.completed_at = None if task.resumable else utcnow_naive()
        task.recovery_metadata = '{"reason":"process_restart"}'
        if not task.resumable:
            db.execute(delete(MetadataDiscoveryLock).where(MetadataDiscoveryLock.task_id == task.id))
            db.execute(update(MetadataDiscovery).where(MetadataDiscovery.job_id==task.id,
                MetadataDiscovery.status.in_(("queued","running"))).values(status="failed",completed_at=utcnow_naive(),error_metadata='[{"code":"process_restart"}]'))
    db.commit()
    return len(jobs)
