from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.database.models import Song
from app.services.library_filters import recent_cutoff


@dataclass(frozen=True, slots=True)
class AlbumAnalytics:
    name: str
    artist: str
    song_count: int
    storage_bytes: int
    year: int | None

    @classmethod
    def from_row(cls, row) -> "AlbumAnalytics | None":
        if row is None:
            return None
        return cls(
            name=row.album,
            artist=row.artist,
            song_count=row.song_count,
            storage_bytes=row.storage_bytes or 0,
            year=row.year,
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "artist": self.artist,
            "song_count": self.song_count,
            "storage_bytes": self.storage_bytes,
            "year": self.year,
        }


class LibraryAnalyticsService:
    """Calculates reusable Library metrics using database aggregates only."""

    def calculate(self, db: Session) -> dict:
        available = Song.availability_status == "available"
        overview = db.execute(
            select(
                func.count(Song.id).label("songs"),
                func.count(func.distinct(Song.artist)).label("artists"),
                func.count(func.distinct(Song.genre)).label("genres"),
                func.coalesce(func.sum(Song.file_size), 0).label("storage_bytes"),
                func.avg(Song.bitrate).label("average_bitrate"),
                func.avg(Song.duration).label("average_duration"),
                func.coalesce(
                    func.sum(case((Song.created_at >= recent_cutoff(), 1), else_=0)),
                    0,
                ).label("recently_added"),
            ).where(available)
        ).one()

        album_stats = (
            select(
                Song.album.label("album"),
                func.coalesce(
                    Song.album_artist,
                    Song.artist,
                    "Unknown Artist",
                ).label("artist"),
                func.count(Song.id).label("song_count"),
                func.coalesce(func.sum(Song.file_size), 0).label("storage_bytes"),
                func.max(Song.year).label("year"),
            )
            .where(available, Song.album.is_not(None), Song.album != "")
            .group_by(
                Song.album,
                func.coalesce(Song.album_artist, Song.artist, "Unknown Artist"),
            )
            .subquery()
        )

        albums = db.scalar(select(func.count()).select_from(album_stats)) or 0
        largest = db.execute(
            select(album_stats)
            .order_by(
                album_stats.c.song_count.desc(),
                album_stats.c.storage_bytes.desc(),
                func.lower(album_stats.c.album),
            )
            .limit(1)
        ).first()
        newest = db.execute(
            select(album_stats)
            .where(album_stats.c.year.is_not(None))
            .order_by(album_stats.c.year.desc(), func.lower(album_stats.c.album))
            .limit(1)
        ).first()
        oldest = db.execute(
            select(album_stats)
            .where(album_stats.c.year.is_not(None))
            .order_by(album_stats.c.year.asc(), func.lower(album_stats.c.album))
            .limit(1)
        ).first()

        return {
            "songs": overview.songs,
            "albums": albums,
            "artists": overview.artists,
            "genres": overview.genres,
            "storage_bytes": overview.storage_bytes,
            "average_bitrate": round(overview.average_bitrate or 0),
            "average_duration": round(overview.average_duration or 0, 2),
            "recently_added": overview.recently_added,
            "largest_album": _album_dict(largest),
            "newest_album": _album_dict(newest),
            "oldest_album": _album_dict(oldest),
        }


def _album_dict(row) -> dict | None:
    album = AlbumAnalytics.from_row(row)
    return album.to_dict() if album else None


library_analytics = LibraryAnalyticsService()
