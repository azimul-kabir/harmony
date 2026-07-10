from dataclasses import dataclass, field

from app.domain.metadata.album import AlbumMetadata
from app.domain.metadata.artist import ArtistMetadata


@dataclass(slots=True)
class TrackMetadata:
    title: str

    artists: list[ArtistMetadata] = field(default_factory=list)

    album: AlbumMetadata | None = None

    track_number: int | None = None
    disc_number: int | None = None

    duration_ms: int | None = None

    spotify_track_id: str | None = None

    spotify_url: str | None = None

    isrc: str | None = None

    genre: str | None = None

    lyrics: str | None = None

    cover_url: str | None = None
