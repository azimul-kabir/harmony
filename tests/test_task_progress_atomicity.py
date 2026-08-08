from app.database.models import DownloadJob, Task
from app.database.session import SessionLocal
from app.domain.task import TaskStatus, TaskType
from app.services.task_service import increment_skipped, reconcile_stalled_playlist_tasks


def test_stale_worker_sessions_increment_task_progress_atomically():
    setup = SessionLocal()
    first = SessionLocal()
    second = SessionLocal()
    try:
        task = Task(
            name="Concurrent skips",
            spotify_url="https://example.test/playlist",
            task_type=TaskType.PLAYLIST_SYNC.value,
            status=TaskStatus.RUNNING.value,
            total_items=2,
            completed_items=0,
            skipped_items=0,
            failed_items=0,
        )
        setup.add(task)
        setup.commit()
        task_id = task.id

        first_task = first.get(Task, task_id)
        second_task = second.get(Task, task_id)
        assert first_task.skipped_items == second_task.skipped_items == 0

        increment_skipped(first, first_task)
        increment_skipped(second, second_task)

        setup.expire_all()
        finished = setup.get(Task, task_id)
        assert finished.skipped_items == 2
        assert finished.status == TaskStatus.COMPLETED.value
    finally:
        second.close()
        first.close()
        setup.close()


def test_startup_reconciles_playlist_task_with_all_terminal_jobs():
    db = SessionLocal()
    try:
        task = Task(
            name="Funky Groove Mix",
            spotify_url="https://example.test/playlist",
            task_type=TaskType.PLAYLIST_SYNC.value,
            status=TaskStatus.RUNNING.value,
            total_items=20,
            completed_items=0,
            skipped_items=19,
            failed_items=0,
            current_item="Downloading",
        )
        db.add(task)
        db.flush()
        db.add_all(
            [
                DownloadJob(
                    task_id=task.id,
                    spotify_url=f"https://example.test/track/{index}",
                    title=f"Song {index}",
                    artist="Artist",
                    status="skipped",
                )
                for index in range(2)
            ]
        )
        db.commit()

        assert reconcile_stalled_playlist_tasks(db) == [task.id]

        db.refresh(task)
        assert task.completed_items == 0
        assert task.skipped_items == 20
        assert task.failed_items == 0
        assert task.status == TaskStatus.COMPLETED.value
        assert task.current_item is None
        assert task.completed_at is not None
    finally:
        db.close()
