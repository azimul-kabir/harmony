from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import Song


class LibraryAnalyticsService:
    """Return the small operational Library summary shared by health views."""

    def calculate(self, db: Session) -> dict:
        available = Song.availability_status == "available"
        overview = db.execute(
            select(
                func.count(Song.id).label("songs"),
                func.count(func.distinct(Song.artist)).label("artists"),
                func.coalesce(func.sum(Song.file_size), 0).label("storage_bytes"),
            ).where(available)
        ).one()
        album_groups = (
            select(Song.album, Song.album_artist, Song.artist)
            .where(available, Song.album.is_not(None), Song.album != "")
            .group_by(Song.album, Song.album_artist, Song.artist)
            .subquery()
        )
        albums = db.scalar(select(func.count()).select_from(album_groups)) or 0
        return {
            "songs": int(overview.songs or 0),
            "albums": int(albums),
            "artists": int(overview.artists or 0),
            "storage_bytes": int(overview.storage_bytes or 0),
        }


library_analytics = LibraryAnalyticsService()
