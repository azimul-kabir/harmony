from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)


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
    jobs = relationship("DownloadJob", back_populates="task")
    bulk_items = relationship(
        "BulkOperationItem",
        back_populates="task",
        cascade="all, delete-orphan",
    )


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
