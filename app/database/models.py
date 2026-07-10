from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

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


class DownloadJob(Base):
    __tablename__ = "download_jobs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
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