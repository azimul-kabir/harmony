from dataclasses import dataclass
from enum import Enum

from app.domain.track import Track


class JobStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class QueueStatus(str, Enum):
    CREATED = "created"
    ALREADY_EXISTS = "already_exists"


@dataclass(slots=True)
class DownloadItem:
    track: Track
    priority: int = 0


@dataclass(slots=True)
class DownloadQueue:
    items: list[DownloadItem]

    @property
    def total(self) -> int:
        return len(self.items)
