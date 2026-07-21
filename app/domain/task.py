from enum import StrEnum


class TaskType(StrEnum):
    TRACK_DOWNLOAD = "track_download"
    ALBUM_DOWNLOAD = "album_download"
    PLAYLIST_DOWNLOAD = "playlist_download"
    PLAYLIST_SYNC = "playlist_sync"
    LIBRARY_BULK = "library_bulk"
    LIBRARY_MAINTENANCE = "library_maintenance"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    PAUSED = "paused"       # New state
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    INTERRUPTED = "interrupted"
