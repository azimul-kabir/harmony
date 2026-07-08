from dataclasses import dataclass
from enum import Enum

from app.domain.track import Track


class TrackStatus(str, Enum):
    OWNED = "owned"
    MISSING = "missing"


@dataclass(slots=True)
class ComparedTrack:
    track: Track
    status: TrackStatus


@dataclass(slots=True)
class PlaylistComparison:
    playlist_name: str
    total: int
    owned: int
    missing: int
    tracks: list[ComparedTrack]