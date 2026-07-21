"""Provider-neutral inputs and explainable metadata match results."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ConfidenceLevel = Literal["exact", "high", "medium", "low", "rejected"]


class MatchEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: str
    field: str
    message: str
    points: float = 0
    local_value: Any = None
    candidate_value: Any = None


class SongMatchInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    song_id: int
    title: str | None = None
    artist: str | None = None
    album_artist: str | None = None
    album: str | None = None
    duration_seconds: float | None = None
    track_number: int | None = None
    total_tracks: int | None = None
    disc_number: int | None = None
    total_discs: int | None = None
    release_date: str | None = None
    year: int | None = None
    isrc: str | None = None
    existing_provider_ids: dict[str, str] = Field(default_factory=dict)
    compilation: bool | None = None
    filename: str | None = None
    file_path: str | None = Field(default=None, exclude=True)
    codec: str | None = None
    bitrate: int | None = None


class AlbumMatchInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    album_key: str
    title: str | None = None
    album_artist: str | None = None
    release_date: str | None = None
    year: int | None = None
    track_count: int | None = None
    disc_count: int | None = None
    compilation: bool | None = None
    known_recording_ids: tuple[str, ...] = ()
    existing_provider_ids: dict[str, str] = Field(default_factory=dict)


class ArtistMatchInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    artist_key: str
    name: str
    aliases: tuple[str, ...] = ()
    existing_provider_ids: dict[str, str] = Field(default_factory=dict)


class MatchResult(BaseModel):
    provider: str
    entity_type: Literal["song", "album", "artist"]
    local_entity_id: str
    provider_entity_id: str
    candidate_summary: dict[str, Any]
    score: float = Field(ge=0, le=100)
    confidence_level: ConfidenceLevel
    rank: int = 0
    viable: bool
    ambiguous: bool = False
    hard_rejection: bool = False
    positive_evidence: tuple[MatchEvidence, ...] = ()
    conflicting_evidence: tuple[MatchEvidence, ...] = ()
    unavailable_evidence: tuple[MatchEvidence, ...] = ()
    rejection_reasons: tuple[str, ...] = ()
    search_provenance: tuple[str, ...] = ()
    scoring_version: str
    matcher_version: str
    created_at: datetime
