from pydantic import BaseModel


class SpotDLSong(BaseModel):
    name: str
    artist: str
    artists: list[str]

    album_name: str
    album_artist: str

    duration: int
    year: int | None = None

    track_number: int | None = None
    disc_number: int | None = None

    song_id: str
    url: str

    isrc: str | None = None

    cover_url: str | None = None

    list_name: str | None = None
    list_url: str | None = None
    list_position: int | None = None
    list_length: int | None = None

    album_id: str | None = None
    artist_id: str | None = None