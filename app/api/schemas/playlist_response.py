from pydantic import BaseModel, ConfigDict


class TrackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: str
    artist: str
    album: str | None = None
    album_artist: str | None = None
    track: int | None = None
    disc: int | None = None
    year: int | None = None
    duration: float | None = None
    spotify_track_id: str | None = None
    spotify_url: str | None = None
    isrc: str | None = None


class PlaylistResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    url: str
    track_count: int
    tracks: list[TrackResponse]
