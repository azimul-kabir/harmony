from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session

from app.database.models import Task, TaskItemFailure
from app.database.session import get_db
from app.domain.task import TaskStatus
from app.services.task_service import (
    cancel_task,
    pause_task,
    resume_task,
)
from app.services.task_progress import serialize_task_progress

router = APIRouter(
    prefix="/api/tasks",
    tags=["tasks"],
)

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
    jobs = db.scalars(select(Task).where(Task.task_type.in_(("library_bulk", "library_maintenance")), Task.status.in_(("queued", "running", "cancelling"))).order_by(Task.created_at.desc())).all()
    return [serialize_task_progress(job) for job in jobs]

@router.get("/jobs/recent", summary="List recent Library jobs")
def recent_jobs(limit: int = 25, db: Session = Depends(get_db)):
    jobs = db.scalars(select(Task).where(Task.task_type.in_(("library_bulk", "library_maintenance"))).order_by(Task.created_at.desc()).limit(min(max(limit, 1), 100))).all()
    return [serialize_task_progress(job) for job in jobs]

@router.get("/jobs/{task_id}", summary="Get persistent Library job details")
def job_details(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task or task.task_type not in ("library_bulk", "library_maintenance"):
        raise HTTPException(status_code=404, detail="Library job not found")
    return serialize_task_progress(task)

@router.get("/jobs/{task_id}/failures", summary="Paginate safe per-item Library job failures")
def job_failures(task_id: int, offset: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    if not db.get(Task, task_id): raise HTTPException(status_code=404, detail="Library job not found")
    query = select(TaskItemFailure).where(TaskItemFailure.task_id == task_id).order_by(TaskItemFailure.id.desc())
    total = db.scalar(select(func.count()).select_from(TaskItemFailure).where(TaskItemFailure.task_id == task_id)) or 0
    rows = db.scalars(query.offset(max(offset, 0)).limit(min(max(limit, 1), 100))).all()
    return {"items": [{"id": x.id, "item": x.item_description, "error_code": x.error_code, "message": x.message, "created_at": x.created_at} for x in rows], "total": total, "offset": offset, "limit": limit}

@router.post("/jobs/{task_id}/cancel", summary="Request cooperative Library job cancellation")
def cancel_job(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task or task.task_type not in ("library_bulk", "library_maintenance"): raise HTTPException(status_code=404, detail="Library job not found")
    cancel_task(db, task)
    return serialize_task_progress(task)

@router.get("/library-activity", summary="Recent completed Library activity")
def library_activity(limit: int = 20, db: Session = Depends(get_db)):
    return recent_jobs(limit, db)

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
