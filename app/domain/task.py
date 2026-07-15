from enum import StrEnum


class TaskType(StrEnum):
    TRACK_DOWNLOAD = "track_download"
    ALBUM_DOWNLOAD = "album_download"
    PLAYLIST_DOWNLOAD = "playlist_download"
    PLAYLIST_SYNC = "playlist_sync"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"       # New state
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
