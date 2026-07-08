from pydantic import BaseModel, ConfigDict

from app.api.schemas.playlist_response import TrackResponse
from app.domain.comparison import TrackStatus


class ComparedTrackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    track: TrackResponse
    status: TrackStatus


class PlaylistComparisonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    playlist_name: str
    total: int
    owned: int
    missing: int
    tracks: list[ComparedTrackResponse]