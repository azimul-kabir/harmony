from dataclasses import dataclass, field

from app.domain.track import Track


@dataclass(slots=True)
class Playlist:
    name: str
    url: str
    tracks: list[Track] = field(default_factory=list)

    @property
    def track_count(self) -> int:
        return len(self.tracks)
