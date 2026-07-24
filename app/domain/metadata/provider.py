from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExternalId(BaseModel):
    model_config = ConfigDict(frozen=True)
    namespace: str
    value: str


class Relationship(BaseModel):
    model_config = ConfigDict(frozen=True)
    relation_type: str
    target_type: str
    target_id: str
    target_name: str | None = None
    direction: str | None = None


class CandidateBase(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider: str
    provider_entity_id: str
    title: str
    aliases: tuple[str, ...] = ()
    genres: tuple[str, ...] = ()
    external_ids: tuple[ExternalId, ...] = ()
    relationships: tuple[Relationship, ...] = ()
    confidence: None = None


class RecordingCandidate(CandidateBase):
    entity_type: Literal["recording"] = "recording"
    artist: str | None = None
    album: str | None = None
    duration_seconds: float | None = None
    track_number: int | None = None
    disc_number: int | None = None
    release_date: str | None = None
    release_group: str | None = None
    album_artist: str | None = None
    total_tracks: int | None = None
    total_discs: int | None = None
    original_release_date: str | None = None
    year: int | None = None
    isrc: str | None = None
    recording_disambiguation: str | None = None
    release_disambiguation: str | None = None
    compilation: bool | None = None
    release_id: str | None = None
    release_group_id: str | None = None
    artist_id: str | None = None
    release_artist_id: str | None = None
    release_context: str | None = None


class ReleaseCandidate(CandidateBase):
    entity_type: Literal["release"] = "release"
    artist: str | None = None
    release_date: str | None = None
    release_group: str | None = None
    track_count: int | None = None
    disc_count: int | None = None


class ArtistCandidate(CandidateBase):
    entity_type: Literal["artist"] = "artist"
    sort_name: str | None = None
    artist_type: str | None = None
    country: str | None = None
    disambiguation: str | None = None


class ReleaseGroupCandidate(CandidateBase):
    entity_type: Literal["release_group"] = "release_group"
    artist: str | None = None
    primary_type: str | None = None
    secondary_types: tuple[str, ...] = ()
    first_release_date: str | None = None


ProviderCandidate = RecordingCandidate | ReleaseCandidate | ArtistCandidate | ReleaseGroupCandidate


class CandidatePage(BaseModel):
    items: list[ProviderCandidate]
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
    total: int = Field(ge=0)
