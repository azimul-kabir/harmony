from dataclasses import dataclass, field

from app.domain.track import Track


@dataclass(slots=True)
class Playlist:
    name: str
    url: str | None = None
    tracks: list[Track] = field(default_factory=list)