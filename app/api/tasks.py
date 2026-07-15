from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Task
from app.database.session import get_db
from app.domain.task import TaskStatus
from app.services.task_service import (
    cancel_task,
    pause_task,
    resume_task,
)

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
