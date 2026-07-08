from dataclasses import dataclass


@dataclass(slots=True)
class Track:
    title: str
    artist: str

    album: str | None = None
    album_artist: str | None = None

    track: int | None = None
    disc: int | None = None

    year: int | None = None
    genre: str | None = None
    duration: float | None = None

    # External identifiers
    spotify_id: str | None = None
    spotify_url: str | None = None
    isrc: str | None = None

    # Local library
    path: str | None = None