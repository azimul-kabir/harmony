from dataclasses import dataclass
from enum import Enum


class QueueStatus(str, Enum):
    CREATED = "created"
    ALREADY_QUEUED = "already_queued"


@dataclass(slots=True)
class QueueResult:
    job_id: int
    status: QueueStatus
