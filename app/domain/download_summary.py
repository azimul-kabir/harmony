from dataclasses import dataclass, field

from app.domain.track_download_result import TrackDownloadResult


@dataclass(slots=True)
class PlaylistDownloadSummary:
    playlist_name: str

    total: int

    owned: int
    already_queued: int
    queued: int
    failed: int = 0

    tracks: list[TrackDownloadResult] = field(default_factory=list)
