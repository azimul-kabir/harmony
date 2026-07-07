from dataclasses import dataclass

from app.domain.track import Track


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