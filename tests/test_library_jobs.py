from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.tasks import (
    AcknowledgeJobsRequest,
    acknowledge_job,
    acknowledge_jobs,
    job_failures,
    library_activity,
)
from app.database.models import Task, TaskItemFailure
from app.database.session import SessionLocal
from app.domain.task import TaskStatus, TaskType
from app.services.library_health import library_health
from app.services.task_progress import serialize_task_progress
from app.services.task_service import (
    cancel_task,
    cleanup_library_jobs,
    create_task,
    record_item_failure,
    recover_library_jobs,
)
from app.main import app


def _maintenance_task(db, *, status=TaskStatus.COMPLETED, index=0):
    task = create_task(
        db,
        name=f"Maintenance {index}",
        spotify_url=f"library://maintenance/test-{index}",
        task_type=TaskType.LIBRARY_MAINTENANCE,
        total_items=1,
    )
    task.status = status.value
    if status in {
        TaskStatus.COMPLETED,
        TaskStatus.COMPLETED_WITH_ERRORS,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.INTERRUPTED,
    }:
        task.completed_items = 1 if status == TaskStatus.COMPLETED else 0
    db.commit()
    return task


def test_job_progress_contract_exposes_persistent_fields():
    with SessionLocal() as db:
        task = _maintenance_task(db)
        task.initiated_by = "library-health-ui"
        task.recovery_metadata = '{"reason":"test"}'
        db.commit()

        result = serialize_task_progress(task)

        assert result["job_id"] == task.id
        assert result["job_type"] == "library_maintenance"
        assert result["processed_items"] == result["successful_items"] == 1
        assert result["progress_percentage"] == 100
        assert result["recovery_metadata"] == {"reason": "test"}


def test_running_job_cancellation_is_cooperative():
    with SessionLocal() as db:
        task = _maintenance_task(db, status=TaskStatus.RUNNING)

        cancel_task(db, task)

        assert task.status == "cancelling"
        assert task.cancellation_requested_at is not None


def test_restart_interrupts_non_resumable_and_requeues_resumable_jobs():
    with SessionLocal() as db:
        interrupted = _maintenance_task(db, status=TaskStatus.RUNNING, index=1)
        resumable = _maintenance_task(db, status=TaskStatus.COMPLETED, index=2)
        resumable.status = "running"
        resumable.resumable = True
        db.commit()

        assert recover_library_jobs(db) == 2
        db.refresh(interrupted)
        db.refresh(resumable)

        assert interrupted.status == "interrupted"
        assert interrupted.completed_at is not None
        assert resumable.status == "queued"
        assert resumable.completed_at is None


def test_duplicate_and_conflicting_library_jobs_are_rejected():
    with SessionLocal() as db:
        first = library_health.create_action(db, "refresh")

        for action in ("refresh", "verify"):
            try:
                library_health.create_action(db, action)
            except ValueError as error:
                assert str(error).startswith("CONFLICTING_JOB")
            else:
                raise AssertionError("conflicting job was accepted")

        cancel_task(db, first)
        assert library_health.create_action(db, "verify").status == "queued"


def test_item_failures_are_bounded_and_paginated():
    with SessionLocal() as db:
        task = _maintenance_task(db, status=TaskStatus.FAILED)
        for index in range(105):
            record_item_failure(db, task, f"song-{index}", "VERIFY_FAILED", "Could not verify file")
            db.commit()

        assert db.query(TaskItemFailure).filter_by(task_id=task.id).count() == 100
        page = job_failures(task.id, offset=10, limit=7, db=db)
        assert page["total"] == 100
        assert page["offset"] == 10
        assert page["limit"] == 7
        assert len(page["items"]) == 7
        assert {item["error_code"] for item in page["items"]} == {"VERIFY_FAILED"}


def test_activity_excludes_active_jobs():
    with SessionLocal() as db:
        _maintenance_task(db, status=TaskStatus.COMPLETED, index=1)
        _maintenance_task(db, status=TaskStatus.RUNNING, index=2)

        activity = library_activity(limit=20, db=db)

        assert len(activity) == 1
        assert activity[0]["status"] == "completed"


def test_library_health_page_exposes_recent_activity_show_more():
    response = TestClient(app).get("/library/health")

    assert response.status_code == 200
    assert 'id="library-activity-show-more"' in response.text
    assert "Show 10 more" in response.text


def test_activity_can_filter_all_attention_jobs_by_type():
    with SessionLocal() as db:
        _maintenance_task(
            db,
            status=TaskStatus.COMPLETED_WITH_ERRORS,
            index=1,
        )
        _maintenance_task(db, status=TaskStatus.FAILED, index=2)
        _maintenance_task(db, status=TaskStatus.COMPLETED, index=3)
        bulk = create_task(
            db,
            name="Bulk failure",
            spotify_url="library://bulk/delete",
            task_type=TaskType.LIBRARY_BULK,
            total_items=1,
        )
        bulk.status = TaskStatus.FAILED.value
        db.commit()

        activity = library_activity(
            limit=100,
            attention_only=True,
            job_type=TaskType.LIBRARY_MAINTENANCE.value,
            db=db,
        )

        assert len(activity) == 2
        assert {item["status"] for item in activity} == {
            "completed_with_errors",
            "failed",
        }
        assert {item["type"] for item in activity} == {
            "library_maintenance"
        }


def test_reviewed_jobs_leave_attention_but_keep_history():
    with SessionLocal() as db:
        first = _maintenance_task(
            db,
            status=TaskStatus.COMPLETED_WITH_ERRORS,
            index=1,
        )
        second = _maintenance_task(
            db,
            status=TaskStatus.FAILED,
            index=2,
        )

        acknowledged = acknowledge_job(first.id, db)

        assert acknowledged["reviewed_at"] is not None
        attention = library_activity(
            limit=100,
            attention_only=True,
            job_type=TaskType.LIBRARY_MAINTENANCE.value,
            db=db,
        )
        assert [item["id"] for item in attention] == [second.id]
        history = library_activity(limit=100, db=db)
        assert {item["id"] for item in history} == {first.id, second.id}


def test_category_acknowledgement_marks_only_requested_job_type():
    with SessionLocal() as db:
        maintenance = _maintenance_task(
            db,
            status=TaskStatus.FAILED,
            index=1,
        )
        bulk = create_task(
            db,
            name="Bulk failure",
            spotify_url="library://bulk/delete",
            task_type=TaskType.LIBRARY_BULK,
            total_items=1,
        )
        bulk.status = TaskStatus.FAILED.value
        db.commit()

        result = acknowledge_jobs(
            AcknowledgeJobsRequest(job_type="library_maintenance"),
            db,
        )

        assert result["acknowledged"] == 1
        db.refresh(maintenance)
        db.refresh(bulk)
        assert maintenance.reviewed_at is not None
        assert bulk.reviewed_at is None


def test_cleanup_retains_newest_terminal_jobs_and_active_jobs():
    with SessionLocal() as db:
        terminal_ids = [_maintenance_task(db, index=index).id for index in range(5)]
        active = _maintenance_task(db, status=TaskStatus.RUNNING, index=99)

        assert cleanup_library_jobs(db, retain=2) == 3
        remaining_terminal = db.scalars(
            select(Task.id).where(Task.id.in_(terminal_ids)).order_by(Task.id)
        ).all()

        assert remaining_terminal == terminal_ids[-2:]
        assert db.get(Task, active.id) is not None
