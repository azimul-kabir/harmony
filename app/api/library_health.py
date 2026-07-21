from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.models import Task
from app.database.session import get_db
from app.domain.task import TaskType
from app.services.library_health import HEALTH_ACTIONS, library_health
from app.services.task_service import cancel_task
from app.services.task_progress import get_typed_task, serialize_task_progress
from app.api.schemas.library import LibraryHealthResponse, TaskProgressResponse


router = APIRouter(prefix="/api/library/health", tags=["library", "health"])


def _get_task(db: Session, task_id: int) -> Task:
    task = get_typed_task(db, task_id, TaskType.LIBRARY_MAINTENANCE)
    if task is None:
        raise HTTPException(status_code=404, detail="Library maintenance task not found")
    return task


@router.get(
    "",
    response_model=LibraryHealthResponse,
    summary="Get Library health",
    description="Returns index-only completeness metrics and registered health checks.",
)
def health_snapshot(db: Session = Depends(get_db)):
    return library_health.calculate(db)


@router.post(
    "/actions/{action}",
    response_model=TaskProgressResponse,
    summary="Queue Library maintenance",
    description="Queues refresh, rebuild, verification, or artwork-cache maintenance as a durable task.",
)
def start_health_action(action: str, db: Session = Depends(get_db)):
    if action not in HEALTH_ACTIONS:
        raise HTTPException(status_code=404, detail="Library health action not found")
    try:
        task = library_health.create_action(db, action)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return serialize_task_progress(task)


@router.get("/tasks/{task_id}", response_model=TaskProgressResponse, summary="Get maintenance progress")
def health_task(task_id: int, db: Session = Depends(get_db)):
    return serialize_task_progress(_get_task(db, task_id))


@router.post("/tasks/{task_id}/cancel", response_model=TaskProgressResponse, summary="Cancel maintenance")
def cancel_health_task(task_id: int, db: Session = Depends(get_db)):
    task = _get_task(db, task_id)
    cancel_task(db, task)
    return serialize_task_progress(task)
