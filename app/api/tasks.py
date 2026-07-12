from sqlalchemy import select
from fastapi import APIRouter

from app.database.models import Task
from app.database.session import SessionLocal
from app.domain.task import TaskStatus

router = APIRouter(
    prefix="/api/tasks",
    tags=["tasks"],
)


@router.get("")
def list_tasks():
    db = SessionLocal()

    try:
        tasks = (
            db.execute(
                select(Task)
                .where(
                    Task.status.in_(
                        (
                            TaskStatus.QUEUED.value,
                            TaskStatus.RUNNING.value,
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

    finally:
        db.close()