from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database.models import Task, TaskItemFailure
from app.database.session import get_db
from app.domain.task import TaskStatus
from app.core.time import utcnow_naive
from app.services.task_service import (
    cancel_task,
    clear_library_activity,
    pause_task,
    resume_task,
)
from app.services.task_progress import serialize_task_progress

router = APIRouter(
    prefix="/api/tasks",
    tags=["tasks"],
)

LIBRARY_TASK_TYPES = ("library_bulk", "library_maintenance")
ACTIVE_JOB_STATES = ("queued", "running", "cancelling")
TERMINAL_JOB_STATES = ("cancelled", "completed", "completed_with_errors", "failed", "interrupted")
ATTENTION_JOB_STATES = ("completed_with_errors", "failed", "interrupted")


class AcknowledgeJobsRequest(BaseModel):
    job_type: str


class ClearLibraryActivityRequest(BaseModel):
    include_reviewed_attention: bool = False

@router.get("")
def list_tasks(db: Session = Depends(get_db)):
    tasks = (
        db.execute(
            select(Task)
            .where(
                Task.status.in_(
                    (
                        TaskStatus.QUEUED.value,
                        TaskStatus.RUNNING.value,
                        TaskStatus.PAUSED.value,
                    )
                )
            )
            .order_by(Task.created_at.desc())
        )
        .scalars()
        .all()
    )

    return [
        {
            "id": task.id,
            "name": task.name,
            "status": task.status,
            "total": task.total_items,
            "completed": task.completed_items,
            "failed": task.failed_items,
            "skipped": task.skipped_items,
            "current": task.current_item,
            "type": task.task_type,
        }
        for task in tasks
    ]

@router.get("/jobs/active", summary="List active persistent Library jobs")
def active_jobs(db: Session = Depends(get_db)):
    jobs = db.scalars(select(Task).where(Task.task_type.in_(LIBRARY_TASK_TYPES), Task.status.in_(ACTIVE_JOB_STATES)).order_by(Task.created_at.desc())).all()
    return [serialize_task_progress(job) for job in jobs]

@router.get("/jobs/recent", summary="List recent Library jobs")
def recent_jobs(limit: int = 25, db: Session = Depends(get_db)):
    jobs = db.scalars(select(Task).where(Task.task_type.in_(LIBRARY_TASK_TYPES)).order_by(Task.created_at.desc()).limit(min(max(limit, 1), 100))).all()
    return [serialize_task_progress(job) for job in jobs]


@router.post("/jobs/clear", summary="Clear safe terminal Library activity")
def clear_jobs(
    request: ClearLibraryActivityRequest,
    db: Session = Depends(get_db),
):
    return clear_library_activity(
        db,
        include_reviewed_attention=request.include_reviewed_attention,
    )


@router.get("/jobs/{task_id}", summary="Get persistent Library job details")
def job_details(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task or task.task_type not in LIBRARY_TASK_TYPES:
        raise HTTPException(status_code=404, detail="Library job not found")
    return serialize_task_progress(task)


@router.post("/jobs/{task_id}/acknowledge", summary="Mark a Library job reviewed")
def acknowledge_job(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if (
        not task
        or task.task_type not in LIBRARY_TASK_TYPES
        or task.status not in ATTENTION_JOB_STATES
    ):
        raise HTTPException(
            status_code=404,
            detail="Reviewable Library job not found",
        )
    task.reviewed_at = utcnow_naive()
    db.commit()
    return serialize_task_progress(task)


@router.post("/jobs/acknowledge", summary="Mark a category of Library jobs reviewed")
def acknowledge_jobs(
    request: AcknowledgeJobsRequest,
    db: Session = Depends(get_db),
):
    if request.job_type not in LIBRARY_TASK_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported Library job type")
    tasks = db.scalars(
        select(Task).where(
            Task.task_type == request.job_type,
            Task.status.in_(ATTENTION_JOB_STATES),
            Task.reviewed_at.is_(None),
        )
    ).all()
    reviewed_at = utcnow_naive()
    for task in tasks:
        task.reviewed_at = reviewed_at
    db.commit()
    return {"acknowledged": len(tasks), "job_type": request.job_type}

@router.get("/jobs/{task_id}/failures", summary="Paginate safe per-item Library job failures")
def job_failures(task_id: int, offset: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task or task.task_type not in LIBRARY_TASK_TYPES:
        raise HTTPException(status_code=404, detail="Library job not found")
    safe_offset = max(offset, 0)
    safe_limit = min(max(limit, 1), 100)
    query = select(TaskItemFailure).where(TaskItemFailure.task_id == task_id).order_by(TaskItemFailure.id.desc())
    total = db.scalar(select(func.count()).select_from(TaskItemFailure).where(TaskItemFailure.task_id == task_id)) or 0
    rows = db.scalars(query.offset(safe_offset).limit(safe_limit)).all()
    return {"items": [{"id": x.id, "item": x.item_description, "error_code": x.error_code, "message": x.message, "created_at": x.created_at} for x in rows], "total": total, "offset": safe_offset, "limit": safe_limit}

@router.post("/jobs/{task_id}/cancel", summary="Request cooperative Library job cancellation")
def cancel_job(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task or task.task_type not in LIBRARY_TASK_TYPES: raise HTTPException(status_code=404, detail="Library job not found")
    cancel_task(db, task)
    return serialize_task_progress(task)

@router.get("/library-activity", summary="Recent completed Library activity")
def library_activity(
    limit: int = 20,
    attention_only: bool = False,
    job_type: str | None = None,
    db: Session = Depends(get_db),
):
    if job_type is not None and job_type not in LIBRARY_TASK_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported Library job type")
    statuses = ATTENTION_JOB_STATES if attention_only else TERMINAL_JOB_STATES
    statement = select(Task).where(
        Task.task_type.in_(LIBRARY_TASK_TYPES),
        Task.status.in_(statuses),
    )
    if job_type is not None:
        statement = statement.where(Task.task_type == job_type)
    if attention_only:
        statement = statement.where(Task.reviewed_at.is_(None))
    jobs = db.scalars(
        statement
        .order_by(Task.completed_at.desc(), Task.id.desc())
        .limit(min(max(limit, 1), 100))
    ).all()
    return [serialize_task_progress(job) for job in jobs]

@router.post("/{task_id}/pause")
def pause(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    pause_task(db, task)
    return {"status": "success", "task_id": task_id, "new_state": TaskStatus.PAUSED.value}

@router.post("/{task_id}/resume")
def resume(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    resume_task(db, task)
    return {"status": "success", "task_id": task_id, "new_state": TaskStatus.QUEUED.value}

@router.post("/{task_id}/cancel")
def cancel(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    cancel_task(db, task)
    return {"status": "success", "task_id": task_id, "new_state": TaskStatus.CANCELLED.value}
