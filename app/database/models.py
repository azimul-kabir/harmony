from datetime import datetime
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)
from app.domain.task import (
    TaskStatus,
    TaskType,
)
from app.database.base import Base
from app.domain.download import JobStatus
from app.core.time import utcnow_naive

class Song(Base):
    __tablename__ = "songs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String, unique=True, index=True)
    filename: Mapped[str] = mapped_column(String)
    artist: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    album_artist: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    album: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    spotify_track_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True, index=True)
    spotify_album_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    isrc: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    track: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    genre: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    codec: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    modified_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_modified: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metadata_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    artwork_status: Mapped[str] = mapped_column(String, nullable=False, default="missing")
    artwork_id: Mapped[int | None] = mapped_column(
        ForeignKey("artwork.id"), nullable=True, index=True
    )
    artwork: Mapped["Artwork | None"] = relationship()
    availability_status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="available",
        index=True,
    )
    download_source: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="filesystem",
    )
    
    # Album artwork URL
    cover_url: Mapped[str | None] = mapped_column(String, nullable=True)
    musicbrainz_recording_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utcnow_naive,
        index=True,
    )


class MetadataSuggestion(Base):
    """Provider-neutral proposed metadata; never canonical until separately applied."""
    __tablename__ = "metadata_suggestions"
    __table_args__ = (
        CheckConstraint("entity_type IN ('song', 'album', 'artist')", name="ck_metadata_suggestion_entity_type"),
        CheckConstraint("status IN ('pending', 'accepted', 'rejected', 'superseded', 'applied', 'apply_failed')", name="ck_metadata_suggestion_status"),
        CheckConstraint("confidence_level IN ('exact', 'high', 'medium', 'low', 'rejected')", name="ck_metadata_suggestion_confidence_level"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_metadata_suggestion_confidence"),
        Index("ix_metadata_suggestions_entity", "entity_type", "entity_id", "field_name"),
        Index("ix_metadata_suggestions_pending", "status", "created_at"),
        Index(
            "uq_metadata_suggestions_current_review",
            "entity_type", "entity_id", "field_name",
            unique=True,
            sqlite_where=text("status IN ('accepted', 'applied')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    field_name: Mapped[str] = mapped_column(String(80), nullable=False)
    current_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    provider_entity_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    match_explanation: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    positive_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    conflicting_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow_naive, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by_job_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)


class MetadataHistory(Base):
    """Immutable audit record for a canonical metadata change."""
    __tablename__ = "metadata_history"
    __table_args__ = (
        CheckConstraint("entity_type IN ('song', 'album', 'artist')", name="ck_metadata_history_entity_type"),
        Index("ix_metadata_history_entity", "entity_type", "entity_id", "changed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    field_name: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_entity_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow_naive, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    change_source: Mapped[str] = mapped_column(String(120), nullable=False)
    audio_file_modified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reversible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reversal_of_history_id: Mapped[int | None] = mapped_column(ForeignKey("metadata_history.id", ondelete="SET NULL"), nullable=True)


class Artwork(Base):
    __tablename__ = "artwork"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    cache_path: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    original_url: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow_naive, onupdate=utcnow_naive
    )

class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index(
            "uq_tasks_active_resource_key",
            "resource_key",
            unique=True,
            sqlite_where=text("resource_key IS NOT NULL AND status IN ('queued', 'running', 'cancelling')"),
        ),
    )
    source: Mapped["SyncSource | None"] = relationship(back_populates="tasks")
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    spotify_url: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sync_sources.id"), nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String, default=TaskType.TRACK_DOWNLOAD.value, nullable=False)
    status: Mapped[str] = mapped_column(String, default=TaskStatus.QUEUED.value, nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    completed_items: Mapped[int] = mapped_column(Integer, default=0)
    skipped_items: Mapped[int] = mapped_column(Integer, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, default=0)
    current_item: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    operation_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_path: Mapped[str | None] = mapped_column(String, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    initiated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    resource_key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    resumable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recovery_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)
    jobs = relationship("DownloadJob", back_populates="task")
    bulk_items = relationship(
        "BulkOperationItem",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    item_failures = relationship("TaskItemFailure", back_populates="task", cascade="all, delete-orphan")


class TaskItemFailure(Base):
    """Bounded, user-safe diagnostics for a task item."""
    __tablename__ = "task_item_failures"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    item_description: Mapped[str] = mapped_column(String(500), nullable=False)
    error_code: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, nullable=False)
    task: Mapped["Task"] = relationship(back_populates="item_failures")


class BulkOperationItem(Base):
    __tablename__ = "bulk_operation_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    song_id: Mapped[int | None] = mapped_column(ForeignKey("songs.id"), nullable=True, index=True)
    original_path: Mapped[str] = mapped_column(String, nullable=False)
    result_path: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    task: Mapped["Task"] = relationship(back_populates="bulk_items")
    song: Mapped["Song | None"] = relationship()

class DownloadJob(Base):
    __tablename__ = "download_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    task = relationship("Task", back_populates="jobs")
    spotify_url: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    artist: Mapped[str] = mapped_column(String, nullable=False)
    spotify_track_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    spotify_album_id: Mapped[str | None] = mapped_column(String, nullable=True)
    album: Mapped[str | None] = mapped_column(String, nullable=True)
    album_artist: Mapped[str | None] = mapped_column(String, nullable=True)
    track: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    isrc: Mapped[str | None] = mapped_column(String, nullable=True)
    
    # Album artwork URL
    cover_url: Mapped[str | None] = mapped_column(String, nullable=True)
    
    status: Mapped[str] = mapped_column(String, default=JobStatus.QUEUED.value, nullable=False, index=True)
    output_file: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

class SyncSource(Base):
    __tablename__ = "sync_sources"
    tasks: Mapped[list["Task"]] = relationship(back_populates="source")
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    spotify_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    spotify_url: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow_naive)

class Playlist(Base):
    __tablename__ = "playlists"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    spotify_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    spotify_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String, nullable=True)
    owner: Mapped[str | None] = mapped_column(String, nullable=True)
    track_count: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)
    tracks: Mapped[list["PlaylistTrack"]] = relationship(
        back_populates="playlist", 
        cascade="all, delete-orphan", 
        order_by="PlaylistTrack.position"
    )

class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"
    playlist_id: Mapped[int] = mapped_column(ForeignKey("playlists.id"), primary_key=True)
    spotify_track_id: Mapped[str] = mapped_column(String, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    playlist: Mapped["Playlist"] = relationship(back_populates="tracks")

class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    value: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, default="string")
    category: Mapped[str] = mapped_column(String, index=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)
