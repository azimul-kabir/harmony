"""Durable worker for confirmed staged Library imports."""
from __future__ import annotations

import asyncio
import json
import threading
from sqlalchemy import select, update

from app.core.logging import logger
from app.core.time import utcnow_naive
from app.database.models import BulkOperationItem, Task
from app.database.session import SessionLocal
from app.domain.task import TaskStatus, TaskType
from app.services.library_uploads import duplicate_preflight, import_batch, load_batch
from app.services.navidrome import NavidromeClient, NavidromeError
from app.services.task_service import create_task, record_item_failure


def create_import_task(db, *, batch_id: str, selections: list[dict], scan_navidrome: bool) -> Task:
    manifest = load_batch(batch_id)
    available = {item["id"] for item in manifest["items"]}
    if any(item.get("id") not in available for item in selections):
        raise ValueError("One or more staged files are no longer available.")
    task = create_task(
        db, name="Import local music", spotify_url=f"library://upload/{batch_id}",
        task_type=TaskType.LIBRARY_IMPORT, total_items=len(selections),
        operation_payload=json.dumps({"action": "local_import", "batch_id": batch_id, "selections": selections, "scan_navidrome": scan_navidrome}),
        resource_key="library-files", initiated_by="library-upload-ui", resumable=True, commit=False,
    )
    for selection in selections:
        task.bulk_items.append(BulkOperationItem(original_path=selection["id"], status="queued"))
    db.commit(); db.refresh(task)
    return task


class LibraryImportWorker:
    def __init__(self, poll_seconds=.5):
        self.poll_seconds=poll_seconds; self._stop=threading.Event(); self._thread=None
    def start(self):
        if self._thread and self._thread.is_alive(): return
        self._stop.clear(); self._thread=threading.Thread(target=self._run,daemon=True,name="library-import-worker"); self._thread.start()
    def stop(self):
        self._stop.set()
        if self._thread: self._thread.join(timeout=5)
    def _run(self):
        while not self._stop.is_set():
            db=SessionLocal()
            try:
                task=db.scalar(select(Task).where(Task.task_type==TaskType.LIBRARY_IMPORT.value,Task.status==TaskStatus.QUEUED.value).order_by(Task.created_at,Task.id).limit(1))
                if task: self.process_task(db,task); continue
            except Exception: logger.exception("Library import worker recovered from failure")
            finally: db.close()
            self._stop.wait(self.poll_seconds)
    def process_task(self,db,task):
        payload=json.loads(task.operation_payload or "{}"); batch_id=payload["batch_id"]
        selections={item["id"]:item for item in payload.get("selections",[])}
        task.status=TaskStatus.RUNNING.value; task.started_at=task.started_at or utcnow_naive(); db.commit()
        items=db.scalars(select(BulkOperationItem).where(BulkOperationItem.task_id==task.id,BulkOperationItem.status=="queued").order_by(BulkOperationItem.id)).all()
        for row in items:
            db.refresh(task)
            if self._stop.is_set():
                task.status=TaskStatus.QUEUED.value; task.current_item=None; task.recovery_metadata='{"reason":"worker_shutdown"}'; db.commit(); return
            if task.status in (TaskStatus.CANCELLING.value,TaskStatus.CANCELLED.value):
                row.status="cancelled"; task.skipped_items += 1; db.commit(); continue
            item_id=row.original_path; task.current_item=item_id; row.status="running"; row.started_at=utcnow_naive(); db.commit()
            try:
                manifest=load_batch(batch_id)
                duplicate=next((x for x in duplicate_preflight(db,manifest)["items"] if x["item_id"]==item_id),None)
                if duplicate and duplicate["matches"][0]["tier"] in {"exact","strong"}:
                    row.status="skipped"; row.error="An exact or strong Library match appeared before import."; task.skipped_items += 1
                    record_item_failure(db,task,item_id,"DUPLICATE_CONFLICT",row.error)
                else:
                    result=import_batch(db,batch_id,[selections[item_id]])["items"][0]
                    if result["status"]=="imported": row.status="completed"; row.result_path=result["destination"]; task.completed_items += 1
                    else: raise ValueError(result["error"])
            except Exception:
                db.rollback(); task=db.get(Task,task.id); row=db.get(BulkOperationItem,row.id)
                row.status="failed"; row.error="Harmony could not safely import this staged file."; task.failed_items += 1
                record_item_failure(db,task,item_id,"LIBRARY_IMPORT_FAILED",row.error); logger.exception("Library import task {} failed item",task.id)
            row.completed_at=utcnow_naive(); db.commit()
        db.refresh(task); task.current_item=None; task.completed_at=utcnow_naive()
        if task.status==TaskStatus.CANCELLING.value: task.status=TaskStatus.CANCELLED.value
        elif task.failed_items: task.status=TaskStatus.COMPLETED_WITH_ERRORS.value if task.completed_items else TaskStatus.FAILED.value
        elif task.skipped_items and task.error_code: task.status=TaskStatus.COMPLETED_WITH_ERRORS.value
        else: task.status=TaskStatus.COMPLETED.value
        db.commit()
        if task.completed_items and payload.get("scan_navidrome"):
            try: asyncio.run(NavidromeClient().start_scan(full_scan=False))
            except NavidromeError as error: task.error_summary=f"Files imported; Navidrome scan failed: {error}"; task.error_code="NAVIDROME_SCAN_FAILED"; task.status=TaskStatus.COMPLETED_WITH_ERRORS.value; db.commit()


library_import_worker=LibraryImportWorker()
