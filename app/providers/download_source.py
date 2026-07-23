"""Provider-neutral download source contracts.

Only normalized values leave this module; extractor payloads remain local to a
provider implementation.
"""
from dataclasses import dataclass, field
from typing import Protocol

from app.domain.track import Track


@dataclass(frozen=True, slots=True)
class SourceResult:
    provider: str
    item_id: str
    item_type: str
    title: str
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    duration: float | None = None
    year: int | None = None
    track_number: int | None = None
    disc_number: int | None = None
    explicit: bool | None = None
    artwork_url: str | None = None
    source_url: str | None = None
    track_count: int | None = None


class DownloadSource(Protocol):
    identifier: str
    display_name: str

    def detect_url(self, url: str) -> tuple[str, str] | None: ...
    def search(self, query: str, limit: int = 20) -> list[SourceResult]: ...
    def resolve(self, url: str) -> list[Track]: ...
    def download(self, track: Track, output_dir: str): ...
