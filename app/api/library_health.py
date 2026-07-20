from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.models import Task
from app.database.session import get_db
from app.domain.task import TaskType
from app.services.library_health import HEALTH_ACTIONS, library_health
from app.services.task_service import cancel_task


router = APIRouter(prefix="/api/library/health", tags=["library", "health"])


def _task_response(task: Task) -> dict:
    processed = task.completed_items + task.failed_items + task.skipped_items
    return {
        "id": task.id,
        "name": task.name,
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


def _get_task(db: Session, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.task_type != TaskType.LIBRARY_MAINTENANCE.value:
        raise HTTPException(status_code=404, detail="Library maintenance task not found")
    return task


@router.get("")
def health_snapshot(db: Session = Depends(get_db)):
    return library_health.calculate(db)


@router.post("/actions/{action}")
def start_health_action(action: str, db: Session = Depends(get_db)):
    if action not in HEALTH_ACTIONS:
        raise HTTPException(status_code=404, detail="Library health action not found")
    task = library_health.create_action(db, action)
    return _task_response(task)


@router.get("/tasks/{task_id}")
def health_task(task_id: int, db: Session = Depends(get_db)):
    return _task_response(_get_task(db, task_id))


@router.post("/tasks/{task_id}/cancel")
def cancel_health_task(task_id: int, db: Session = Depends(get_db)):
    task = _get_task(db, task_id)
    cancel_task(db, task)
    return _task_response(task)
