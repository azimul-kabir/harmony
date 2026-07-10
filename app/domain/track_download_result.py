from dataclasses import dataclass
from enum import Enum


class TrackDownloadStatus(str, Enum):
    OWNED = "owned"
    QUEUED = "queued"
    ALREADY_QUEUED = "already_queued"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(slots=True)
class TrackDownloadResult:
    title: str
    artist: str
    status: TrackDownloadStatus
    job_id: int | None = None
