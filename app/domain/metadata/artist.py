from dataclasses import dataclass


@dataclass(slots=True)
class ArtistMetadata:
    name: str

    spotify_id: str | None = None
    musicbrainz_id: str | None = None

    sort_name: str | None = None
