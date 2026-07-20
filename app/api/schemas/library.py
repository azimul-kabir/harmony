"""OpenAPI response contracts for the Library Foundation."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TaskProgressResponse(BaseModel):
    id: int
    name: str
    type: str
    status: str
    total: int
    completed: int
    failed: int
    skipped: int
    processed: int
    progress: float = Field(ge=0, le=100)
    current: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class BulkOperationItemResponse(BaseModel):
    id: int
    song_id: int | None
    original_path: str
    result_path: str | None
    status: str
    error: str | None


class BulkTaskResponse(TaskProgressResponse):
    download_url: str | None = None
    items: list[BulkOperationItemResponse]


class HealthCheckResponse(BaseModel):
    id: str
    label: str
    count: int | None
    status: str
    available: bool


class LibraryHealthResponse(BaseModel):
    songs: int
    albums: int
    artists: int
    storage_bytes: int
    missing_artwork: int
    missing_metadata: int
    duplicates: int | None
    health_score: int = Field(ge=0, le=100)
    last_updated: datetime | None
    checks: list[HealthCheckResponse]


class PlaylistSourceResponse(BaseModel):
    id: int
    name: str
    spotify_id: str


class SongResponse(BaseModel):
    id: int
    path: str
    filename: str
    artist: str | None
    album: str | None
    album_artist: str | None
    title: str | None
    track_number: int | None
    disc_number: int | None
    track: int | None
    disc: int | None
    genre: str | None
    year: int | None
    duration: float | None
    bitrate: int | None
    codec: str | None
    sample_rate: int | None
    file_size: int | None
    artwork_status: str
    artwork_id: int | None
    artwork: dict[str, Any] | None
    cover_url: str | None
    date_added: datetime
    recently_added: bool
    last_modified: datetime | None
    last_indexed_at: datetime | None
    availability_status: str
    spotify_track_id: str | None
    musicbrainz_recording_id: str | None
    isrc: str | None
    download_source: str
    playlist_sources: list[PlaylistSourceResponse]


class AlbumProjectionResponse(BaseModel):
    album: str
    artist: str
    cover_url: str | None
    track_count: int
    total_duration: float


class ArtistProjectionResponse(BaseModel):
    artist: str
    song_count: int
    album_count: int
    cover_url: str | None


class SearchPageResponse(BaseModel):
    query: str
    items: list[SongResponse]
    total: int
    limit: int
    offset: int
    filters: dict[str, Any]
