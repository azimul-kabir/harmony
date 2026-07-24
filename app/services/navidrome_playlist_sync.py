from __future__ import annotations

import asyncio
import queue
import threading
import time
from collections.abc import Callable, Iterable

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import logger
from app.database.models import Playlist, SyncSource, Task
from app.database.session import SessionLocal
from app.domain.task import TaskType
from app.services.navidrome import NavidromeClient, NavidromeError
from app.services.playlist_manager import export_m3u


class NavidromePlaylistReimportCoordinator:
    """Batch terminal playlist syncs into two bounded incremental scans."""

    def __init__(
        self,
        *,
        settings=None,
        client_factory: Callable[[], NavidromeClient] = NavidromeClient,
        session_factory=SessionLocal,
    ) -> None:
        self.settings = settings or get_settings()
        self.client_factory = client_factory
        self.session_factory = session_factory
        self._queue: queue.Queue[int | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()

    @property
    def enabled(self) -> bool:
        return bool(
            self.settings.navidrome_playlist_reimport_enabled
            and self.settings.navidrome_url.strip()
            and self.settings.navidrome_username.strip()
            and self.settings.navidrome_password
        )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._worker,
            daemon=True,
            name="navidrome-playlist-sync",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._queue.put(None)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None

    def schedule(self, task_id: int) -> bool:
        if not self.enabled:
            return False
        self._queue.put(task_id)
        logger.info(
            "Queued Navidrome playlist reconciliation for task #{}.",
            task_id,
        )
        return True

    def _worker(self) -> None:
        while not self._stopping.is_set():
            task_id = self._queue.get()
            if task_id is None:
                return
            task_ids = {task_id}
            deadline = time.monotonic() + max(
                0.0,
                float(self.settings.navidrome_playlist_reimport_debounce_seconds),
            )
            while not self._stopping.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    queued_id = self._queue.get(timeout=remaining)
                except queue.Empty:
                    break
                if queued_id is None:
                    return
                task_ids.add(queued_id)
            try:
                asyncio.run(self.reconcile(task_ids))
            except Exception:
                logger.exception(
                    "Unexpected Navidrome playlist reconciliation failure."
                )

    def _playlist_ids(self, task_ids: Iterable[int]) -> list[int]:
        db = self.session_factory()
        try:
            return list(
                db.scalars(
                    select(Playlist.id)
                    .join(
                        SyncSource,
                        SyncSource.spotify_id == Playlist.spotify_id,
                    )
                    .join(Task, Task.source_id == SyncSource.id)
                    .where(
                        Task.id.in_(set(task_ids)),
                        Task.task_type == TaskType.PLAYLIST_SYNC.value,
                    )
                    .order_by(Playlist.id)
                ).all()
            )
        finally:
            db.close()

    def _rewrite_playlists(self, playlist_ids: Iterable[int]) -> int:
        db = self.session_factory()
        try:
            count = 0
            for playlist in db.scalars(
                select(Playlist)
                .where(Playlist.id.in_(set(playlist_ids)))
                .order_by(Playlist.id)
            ).all():
                export_m3u(db, playlist)
                count += 1
            return count
        finally:
            db.close()

    async def _wait_until_idle(self, client: NavidromeClient) -> None:
        deadline = time.monotonic() + max(
            1.0,
            float(self.settings.navidrome_playlist_reimport_scan_timeout_seconds),
        )
        while True:
            status = await client.status()
            if not status.get("reachable"):
                raise NavidromeError(
                    status.get("error") or "Harmony could not reach Navidrome."
                )
            if not status.get("scanning"):
                return
            if time.monotonic() >= deadline:
                raise NavidromeError(
                    "Timed out waiting for the Navidrome scan to finish.",
                    code="navidrome_scan_timeout",
                )
            await asyncio.sleep(
                max(
                    0.1,
                    float(
                        self.settings.navidrome_playlist_reimport_poll_seconds
                    ),
                )
            )

    async def _incremental_scan(self, client: NavidromeClient) -> None:
        await self._wait_until_idle(client)
        await client.start_scan(full_scan=False)
        await self._wait_until_idle(client)

    async def reconcile(self, task_ids: Iterable[int]) -> bool:
        if not self.enabled:
            return False
        playlist_ids = self._playlist_ids(task_ids)
        if not playlist_ids:
            return False
        client = self.client_factory()
        try:
            logger.info(
                "Starting Navidrome media scan for {} completed playlist sync(s).",
                len(playlist_ids),
            )
            await self._incremental_scan(client)
            rewritten = self._rewrite_playlists(playlist_ids)
            logger.info(
                "Re-exported {} M3U playlist(s) after media indexing; "
                "starting playlist import scan.",
                rewritten,
            )
            await self._incremental_scan(client)
            logger.info(
                "Navidrome playlist reconciliation completed for {} playlist(s).",
                rewritten,
            )
            return True
        except NavidromeError as error:
            logger.warning(
                "Navidrome playlist reconciliation did not complete: {}",
                error,
            )
            return False


navidrome_playlist_reimport = NavidromePlaylistReimportCoordinator()
