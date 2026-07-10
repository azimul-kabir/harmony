from dataclasses import dataclass
from datetime import date


@dataclass(slots=True)
class AlbumMetadata:
    title: str

    spotify_id: str | None = None
    musicbrainz_id: str | None = None

    album_artist: str | None = None

    release_date: date | None = None

    cover_url: str | None = None
