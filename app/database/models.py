from datetime import datetime
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Index,
    String,
    Text,
    UniqueConstraint,
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
    navidrome_id: Mapped[str | None] = mapped_column(
        String, nullable=True, unique=True, index=True
    )
    spotify_album_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    isrc: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    track: Mapped[int | None] = mapped_column(Integer, nullable=True)
    track_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disc_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    genre: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    genre_provenance: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    musicbrainz_release_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    musicbrainz_release_group_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    musicbrainz_artist_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    musicbrainz_release_artist_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # Canonical index values only.  They are deliberately not audio tag state.
    release_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    original_release_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    compilation: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utcnow_naive,
        index=True,
    )


class SongSourceIdentity(Base):
    """Provider identities known to refer to one physical library song."""

    __tablename__ = "song_source_identities"
    provider: Mapped[str] = mapped_column(String(80), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    song_id: Mapped[int] = mapped_column(
        ForeignKey("songs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    song: Mapped["Song"] = relationship()



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
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
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
    source_provider: Mapped[str] = mapped_column(String(80), nullable=False, default="spotify", server_default="spotify", index=True)
    source_item_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    artist: Mapped[str] = mapped_column(String, nullable=False)
    spotify_track_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    spotify_album_id: Mapped[str | None] = mapped_column(String, nullable=True)
    album: Mapped[str | None] = mapped_column(String, nullable=True)
    album_artist: Mapped[str | None] = mapped_column(String, nullable=True)
    track: Mapped[int | None] = mapped_column(Integer, nullable=True)
    queue_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    isrc: Mapped[str | None] = mapped_column(String, nullable=True)
    genre: Mapped[str | None] = mapped_column(String, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    spotify_artist_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    genre_provenance: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Album artwork URL
    cover_url: Mapped[str | None] = mapped_column(String, nullable=True)
    
    status: Mapped[str] = mapped_column(String, default=JobStatus.QUEUED.value, nullable=False, index=True)
    output_file: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    # Public outcome fields are deliberately short and structured.  `error` keeps
    # server-side diagnostics and is never returned verbatim by the API.
    reason_code: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    reason_message: Mapped[str | None] = mapped_column(String, nullable=True)
    failure_stage: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    # Keep the ORM declaration aligned with 20260722_0017: queued rows get a
    # non-terminal ``False`` default both through SQLAlchemy and directly in SQL.
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    technical_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    manual_fallback_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Live telemetry is intentionally provider-neutral.  Providers may leave
    # byte-oriented values null when they cannot report them reliably.
    pipeline_stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    progress_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    worker_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    bytes_downloaded: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transfer_rate_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eta_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

class SyncSource(Base):
    __tablename__ = "sync_sources"
    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_sync_source_provider_external_id"),)
    tasks: Mapped[list["Task"]] = relationship(back_populates="source")
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    spotify_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    spotify_url: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="spotify", index=True)
    external_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_sync_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    auto_sync_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=360)
    auto_sync_last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow_naive)
    schedule_runs: Mapped[list["ScheduleRun"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class ScheduleRun(Base):
    __tablename__ = "schedule_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sync_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow_naive)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped["SyncSource"] = relationship(back_populates="schedule_runs")
    task: Mapped["Task | None"] = relationship()

class Playlist(Base):
    __tablename__ = "playlists"
    __table_args__ = (UniqueConstraint("source_provider", "source_external_id", name="uq_playlist_source_identity"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    spotify_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    source_provider: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    source_external_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    spotify_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String, nullable=True)
    owner: Mapped[str | None] = mapped_column(String, nullable=True)
    track_count: Mapped[int] = mapped_column(Integer, default=0)
    navidrome_playlist_id: Mapped[str | None] = mapped_column(
        String, nullable=True, unique=True, index=True
    )
    navidrome_sync_status: Mapped[str | None] = mapped_column(String, nullable=True)
    navidrome_synced_track_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    navidrome_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    navidrome_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
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
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    artist: Mapped[str | None] = mapped_column(String, nullable=True)
    album: Mapped[str | None] = mapped_column(String, nullable=True)
    album_artist: Mapped[str | None] = mapped_column(String, nullable=True)
    track_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    playlist: Mapped["Playlist"] = relationship(back_populates="tracks")

class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    value: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, default="string")
    category: Mapped[str] = mapped_column(String, index=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)
