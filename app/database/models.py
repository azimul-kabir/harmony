from datetime import datetime

from sqlalchemy import (
    Boolean,
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


class Song(Base):
    __tablename__ = "songs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    path: Mapped[str] = mapped_column(
        String,
        unique=True,
        index=True,
    )

    filename: Mapped[str] = mapped_column(
        String,
    )

    artist: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    album_artist: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    album: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    title: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    spotify_track_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        unique=True,
        index=True,
    )

    spotify_album_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        index=True,
    )

    isrc: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        index=True,
    )

    track: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    disc: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    year: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    genre: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    duration: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    file_size: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    modified_time: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )


class Task(Base):
    __tablename__ = "tasks"

    source: Mapped["SyncSource | None"] = relationship(
        back_populates="tasks",
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    name: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    spotify_url: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sync_sources.id"),
        nullable=True,
        index=True,
    )

    task_type: Mapped[str] = mapped_column(
        String,
        default=TaskType.TRACK_DOWNLOAD.value,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String,
        default=TaskStatus.QUEUED.value,
        nullable=False,
    )

    total_items: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    completed_items: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    skipped_items: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    failed_items: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    current_item: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    jobs = relationship(
        "DownloadJob",
        back_populates="task",
    )


class DownloadJob(Base):
    __tablename__ = "download_jobs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id"),
        nullable=True,
        index=True,
    )

    task = relationship(
        "Task",
        back_populates="jobs",
    )

    spotify_url: Mapped[str] = mapped_column(
        String,
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    artist: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    spotify_track_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        index=True,
    )

    spotify_album_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    album: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    album_artist: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    track: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    disc: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    year: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    isrc: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    # Stored as TEXT in SQLite.
    # The application uses JobStatus enums and converts to/from .value.
    status: Mapped[str] = mapped_column(
        String,
        default=JobStatus.QUEUED.value,
        nullable=False,
        index=True,
    )

    output_file: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )


class SyncSource(Base):
    __tablename__ = "sync_sources"

    tasks: Mapped[list["Task"]] = relationship(
        back_populates="source",
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    type: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    spotify_id: Mapped[str] = mapped_column(
        String,
        nullable=False,
        unique=True,
        index=True,
    )

    spotify_url: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tracks: Mapped[list["PlaylistTrack"]] = relationship(
        back_populates="playlist", 
        cascade="all, delete-orphan", 
        order_by="PlaylistTrack.position"
    )

class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"

    playlist_id: Mapped[int] = mapped_column(ForeignKey("playlists.id"), primary_key=True)
    # We map via Spotify ID so tracks can be added to playlists BEFORE the download finishes
    spotify_track_id: Mapped[str] = mapped_column(String, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    playlist: Mapped["Playlist"] = relationship(back_populates="tracks")
