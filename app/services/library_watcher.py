from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread
import time

from sqlalchemy import select
from watchdog.events import FileSystemEvent, FileSystemEventHandler, FileSystemMovedEvent
from watchdog.observers import Observer

from app.core.config import get_settings
from app.core.logging import logger
from app.database.models import Song
from app.database.session import SessionLocal
from app.services.library_events import library_events
from app.services.library_scanner import index_file
from app.services.tags import SUPPORTED_EXTENSIONS


@dataclass(slots=True)
class PendingFileEvent:
    kind: str
    source: str
    destination: str | None = None
    attempt: int = 0

    @property
    def key(self) -> str:
        return self.destination or self.source


class _WatchdogHandler(FileSystemEventHandler):
    def __init__(self, watcher: "LibraryWatcher") -> None:
        self.watcher = watcher

    def on_created(self, event: FileSystemEvent) -> None:
        self._queue("created", event.src_path, event.is_directory)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._queue("modified", event.src_path, event.is_directory)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._queue("deleted", event.src_path, event.is_directory)

    def on_moved(self, event: FileSystemMovedEvent) -> None:
        if event.is_directory:
            return
        source = str(Path(event.src_path).resolve())
        destination = str(Path(event.dest_path).resolve())
        source_is_audio = _is_audio_path(source)
        destination_is_audio = _is_audio_path(destination)
        if source_is_audio:
            self.watcher.enqueue(
                PendingFileEvent(
                    kind="moved",
                    source=source,
                    destination=destination,
                )
            )
        elif destination_is_audio:
            # Atomic tag writers commonly replace an audio file by moving a
            # temporary non-audio path over it. Treat that as an update.
            self.watcher.enqueue(
                PendingFileEvent(kind="modified", source=destination)
            )

    def _queue(self, kind: str, path: str, is_directory: bool) -> None:
        if is_directory or not _is_audio_path(path):
            return
        self.watcher.enqueue(
            PendingFileEvent(kind=kind, source=str(Path(path).resolve()))
        )


def _is_audio_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def _coalesce(
    existing: PendingFileEvent | None,
    incoming: PendingFileEvent,
) -> PendingFileEvent:
    if existing is None or incoming.kind in {"deleted", "moved"}:
        return incoming
    if existing.kind == "moved" and incoming.kind in {"created", "modified"}:
        return existing
    if existing.kind == "created" and incoming.kind == "modified":
        return existing
    return incoming


def _observer_is_healthy(observer) -> bool:
    emitters = tuple(getattr(observer, "emitters", ()))
    return observer.is_alive() and (
        not emitters or all(emitter.is_alive() for emitter in emitters)
    )


class LibraryWatcher:
    """Incrementally synchronize filesystem changes into the Library Index."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        debounce_seconds: float = 0.75,
        retry_delays: tuple[float, ...] = (0.5, 1.5, 4.0),
        observer_factory=Observer,
    ) -> None:
        settings = get_settings()
        self.root = Path(root or settings.music_path).resolve()
        self.debounce_seconds = debounce_seconds
        self.retry_delays = retry_delays
        self.observer_factory = observer_factory
        self._incoming: Queue[PendingFileEvent] = Queue()
        self._stop = Event()
        self._supervisor: Thread | None = None
        self._processor: Thread | None = None
        self._observer = None
        self._state_lock = Lock()

    @property
    def running(self) -> bool:
        return bool(
            self._supervisor
            and self._supervisor.is_alive()
            and not self._stop.is_set()
        )

    def start(self) -> None:
        with self._state_lock:
            if self.running:
                return

            self.root.mkdir(parents=True, exist_ok=True)
            self._stop.clear()
            self._processor = Thread(
                target=self._process_loop,
                daemon=True,
                name="library-watcher-processor",
            )
            self._supervisor = Thread(
                target=self._supervise,
                daemon=True,
                name="library-watcher-supervisor",
            )
            self._processor.start()
            self._supervisor.start()

    def stop(self) -> None:
        self._stop.set()
        observer = self._observer
        if observer is not None:
            observer.stop()
        if self._supervisor is not None:
            self._supervisor.join(timeout=5)
        if self._processor is not None:
            self._processor.join(timeout=5)

    def enqueue(self, event: PendingFileEvent) -> None:
        self._incoming.put(event)

    def _supervise(self) -> None:
        restart_count = 0
        while not self._stop.is_set():
            observer = None
            try:
                observer = self.observer_factory()
                self._observer = observer
                observer.schedule(_WatchdogHandler(self), str(self.root), recursive=True)
                observer.start()

                if restart_count:
                    logger.info("Library watcher recovered after {} restart(s)", restart_count)
                    library_events.publish(
                        "library.watcher.recovered",
                        root=str(self.root),
                        restart_count=restart_count,
                    )
                else:
                    logger.info("Library watcher started for {}", self.root)

                while not self._stop.wait(1):
                    if not _observer_is_healthy(observer):
                        raise RuntimeError("filesystem observer stopped unexpectedly")
            except Exception as error:
                if self._stop.is_set():
                    break
                restart_count += 1
                logger.exception("Library watcher failed; restarting")
                library_events.publish(
                    "library.watcher.error",
                    root=str(self.root),
                    error=str(error),
                    restart_count=restart_count,
                )
                self._stop.wait(min(5.0, float(restart_count)))
            finally:
                if observer is not None:
                    observer.stop()
                    observer.join(timeout=5)
                self._observer = None

        logger.info("Library watcher stopped")

    def _process_loop(self) -> None:
        pending: dict[str, tuple[float, PendingFileEvent]] = {}

        while not self._stop.is_set() or pending or not self._incoming.empty():
            now = time.monotonic()
            timeout = 0.2
            if pending:
                timeout = max(0.0, min(due for due, _ in pending.values()) - now)
                timeout = min(timeout, 0.2)

            try:
                event = self._incoming.get(timeout=timeout)
                existing = pending.get(event.key)
                pending[event.key] = (
                    time.monotonic() + self.debounce_seconds,
                    _coalesce(existing[1] if existing else None, event),
                )
            except Empty:
                pass

            now = time.monotonic()
            ready = [key for key, (due, _) in pending.items() if due <= now]
            for key in ready:
                _, event = pending.pop(key)
                self._process_with_recovery(event)

    def _process_with_recovery(self, event: PendingFileEvent) -> None:
        while not self._stop.is_set():
            try:
                self._apply(event)
                return
            except Exception as error:
                if event.attempt >= len(self.retry_delays):
                    logger.exception(
                        "Library watcher could not process {} after retries",
                        event.source,
                    )
                    library_events.publish(
                        "library.index.error",
                        operation=event.kind,
                        path=event.source,
                        destination=event.destination,
                        error=str(error),
                    )
                    return

                delay = self.retry_delays[event.attempt]
                event.attempt += 1
                logger.warning(
                    "Library watcher retry {}/{} for {} in {}s: {}",
                    event.attempt,
                    len(self.retry_delays),
                    event.source,
                    delay,
                    error,
                )
                if self._stop.wait(delay):
                    return

    def _apply(self, event: PendingFileEvent) -> None:
        source_is_managed = self._is_managed(event.source)
        destination_is_managed = (
            event.destination is None or self._is_managed(event.destination)
        )
        if not source_is_managed or not destination_is_managed:
            logger.warning("Ignoring watcher event outside music root: {}", event.source)
            return
        db = SessionLocal()
        try:
            if event.kind == "moved":
                self._apply_move(db, event)
                return

            result = index_file(
                db,
                event.source,
                force=event.kind == "modified",
            )
            event_type = {
                "added": "library.track.added",
                "missing": "library.track.missing",
            }.get(result.status, "library.track.updated")
            logger.info("Library watcher {}: {}", event.kind, event.source)
            library_events.publish(
                event_type,
                path=result.path,
                song_id=result.song_id,
                index_status=result.status,
            )
        finally:
            db.close()

    def _is_managed(self, path: str) -> bool:
        candidate = Path(path).resolve()
        return candidate == self.root or candidate.is_relative_to(self.root)

    def _apply_move(self, db, event: PendingFileEvent) -> None:
        assert event.destination is not None
        song = db.scalar(select(Song).where(Song.path == event.source))

        if not _is_audio_path(event.destination) or not Path(event.destination).is_file():
            result = index_file(db, event.source)
            logger.info("Library watcher moved file outside library: {}", event.source)
            library_events.publish(
                "library.track.missing",
                path=event.source,
                destination=event.destination,
                song_id=result.song_id,
                index_status=result.status,
            )
            return

        if song is not None:
            song.path = event.destination
            song.filename = Path(event.destination).name
            db.flush()

        result = index_file(db, event.destination, force=True)
        logger.info("Library watcher renamed {} -> {}", event.source, event.destination)
        library_events.publish(
            "library.track.renamed",
            old_path=event.source,
            path=event.destination,
            song_id=result.song_id,
            index_status=result.status,
        )
