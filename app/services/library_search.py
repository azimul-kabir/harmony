from __future__ import annotations

from dataclasses import dataclass
import re

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database.models import Song
from app.services.library_filters import (
    LibraryFilters,
    raw_filter_clauses,
    raw_sort_clause,
)


SEARCH_FIELDS = (
    "title",
    "artist",
    "album",
    "genre",
    "playlist",
    "filename",
    "spotify_id",
    "musicbrainz_id",
    "isrc",
)
SQLITE_PARAMETER_BATCH = 500

CREATE_SEARCH_INDEX = """
CREATE VIRTUAL TABLE IF NOT EXISTS library_search USING fts5(
    song_id UNINDEXED,
    title,
    artist,
    album,
    genre,
    playlist,
    filename,
    spotify_id,
    musicbrainz_id,
    isrc,
    tokenize = 'unicode61 remove_diacritics 2'
)
"""


SearchFilters = LibraryFilters


@dataclass(frozen=True, slots=True)
class SearchPage:
    song_ids: list[int]
    total: int


class LibrarySearchService:
    """Maintains and queries the FTS projection of the Library Index."""

    def ensure_schema(self, db: Session) -> None:
        db.execute(text(CREATE_SEARCH_INDEX))

    def index_song(self, db: Session, song_id: int) -> None:
        self.ensure_schema(db)
        self._replace_projection(db, [song_id])

    def index_spotify_tracks(self, db: Session, spotify_track_ids: set[str]) -> None:
        if not spotify_track_ids:
            return
        track_ids = tuple(spotify_track_ids)
        for start in range(0, len(track_ids), SQLITE_PARAMETER_BATCH):
            batch = track_ids[start:start + SQLITE_PARAMETER_BATCH]
            song_ids = tuple(db.scalars(
                select(Song.id).where(Song.spotify_track_id.in_(batch))
            ))
            self._replace_projection(db, song_ids)

    def rebuild(self, db: Session) -> int:
        self.ensure_schema(db)
        db.execute(text("DELETE FROM library_search"))
        count = db.scalar(select(func.count(Song.id))) or 0
        self._insert_projection(db)
        return count

    def _replace_projection(self, db: Session, song_ids: tuple[int, ...] | list[int]) -> None:
        ids = tuple(song_ids)
        if not ids:
            return
        for start in range(0, len(ids), SQLITE_PARAMETER_BATCH):
            batch = ids[start:start + SQLITE_PARAMETER_BATCH]
            placeholders = ", ".join(f":song_id_{index}" for index in range(len(batch)))
            parameters = {f"song_id_{index}": song_id for index, song_id in enumerate(batch)}
            db.execute(
                text(f"DELETE FROM library_search WHERE song_id IN ({placeholders})"),
                parameters,
            )
            self._insert_projection(
                db,
                where=f"WHERE songs.id IN ({placeholders})",
                parameters=parameters,
            )

    def _insert_projection(
        self,
        db: Session,
        *,
        where: str = "",
        parameters: dict[str, object] | None = None,
    ) -> None:
        db.execute(
            text(
                f"""
                INSERT INTO library_search (
                    song_id, title, artist, album, genre, playlist, filename,
                    spotify_id, musicbrainz_id, isrc
                )
                SELECT
                    songs.id,
                    coalesce(songs.title, ''),
                    coalesce(songs.artist, ''),
                    coalesce(songs.album, ''),
                    coalesce(songs.genre, ''),
                    coalesce(playlist_sources.names, ''),
                    coalesce(songs.filename, ''),
                    coalesce(songs.spotify_track_id, ''),
                    coalesce(songs.musicbrainz_recording_id, ''),
                    coalesce(songs.isrc, '')
                FROM songs
                LEFT JOIN (
                    SELECT playlist_tracks.spotify_track_id,
                           group_concat(playlists.name, ' ') AS names
                    FROM playlist_tracks
                    JOIN playlists ON playlists.id = playlist_tracks.playlist_id
                    GROUP BY playlist_tracks.spotify_track_id
                ) AS playlist_sources
                  ON playlist_sources.spotify_track_id = songs.spotify_track_id
                {where}
                """
            ),
            parameters or {},
        )

    def search(
        self,
        db: Session,
        query: str,
        *,
        filters: SearchFilters | None = None,
        sort_by: str = "relevance",
        limit: int = 50,
        offset: int = 0,
    ) -> SearchPage:
        self.ensure_schema(db)
        expression = _fts_expression(query)
        if not expression:
            return SearchPage(song_ids=[], total=0)

        filters = filters or SearchFilters()
        filter_clauses, filter_parameters = raw_filter_clauses(filters)
        clauses = ["library_search MATCH :query", *filter_clauses]
        parameters: dict[str, object] = {"query": expression, **filter_parameters}

        where = " AND ".join(clauses)
        total = db.execute(
            text(
                f"""SELECT count(*) FROM library_search
                JOIN songs ON songs.id = library_search.song_id
                WHERE {where}"""
            ),
            parameters,
        ).scalar_one()

        rows = db.execute(
            text(
                f"""SELECT songs.id FROM library_search
                JOIN songs ON songs.id = library_search.song_id
                WHERE {where}
                ORDER BY {raw_sort_clause(sort_by, relevance_default=True)}
                LIMIT :limit OFFSET :offset"""
            ),
            {**parameters, "limit": limit, "offset": offset},
        ).all()
        return SearchPage(song_ids=[row[0] for row in rows], total=total)


def _fts_expression(query: str) -> str:
    tokens = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
    return " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens)


library_search = LibrarySearchService()
