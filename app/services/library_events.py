from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from queue import Empty, Full, Queue
from threading import Lock
from uuid import uuid4

from app.core.logging import logger


@dataclass(frozen=True, slots=True)
class LibraryEvent:
    id: str
    type: str
    occurred_at: str
    payload: dict

    def to_dict(self) -> dict:
        return asdict(self)


class LibraryEventBroker:
    """Thread-safe fan-out for transient Library notifications.

    The broker deliberately owns no business state. The persistent Library Index
    remains authoritative; consumers reconnect and query it after missed events.
    """

    def __init__(self, subscriber_queue_size: int = 100) -> None:
        self._subscriber_queue_size = subscriber_queue_size
        self._subscribers: set[Queue[LibraryEvent]] = set()
        self._lock = Lock()

    def publish(self, event_type: str, **payload) -> LibraryEvent:
        event = LibraryEvent(
            id=str(uuid4()),
            type=event_type,
            occurred_at=datetime.now(UTC).isoformat(),
            payload=payload,
        )

        with self._lock:
            subscribers = tuple(self._subscribers)

        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(event)
                except (Empty, Full):
                    logger.warning("Dropping Library event for a slow subscriber")

        return event

    def subscribe(self) -> Queue[LibraryEvent]:
        subscriber: Queue[LibraryEvent] = Queue(self._subscriber_queue_size)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: Queue[LibraryEvent]) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)


library_events = LibraryEventBroker()
