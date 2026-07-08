from dataclasses import dataclass
from enum import Enum

from app.domain.track import Track


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


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