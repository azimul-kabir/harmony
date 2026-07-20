from __future__ import annotations

from dataclasses import dataclass
import re

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database.models import Playlist, PlaylistTrack, Song
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
        song = db.get(Song, song_id)
        db.execute(
            text("DELETE FROM library_search WHERE song_id = :song_id"),
            {"song_id": song_id},
        )
        if song is None:
            return

        playlists = db.scalars(
            select(Playlist.name)
            .join(PlaylistTrack, PlaylistTrack.playlist_id == Playlist.id)
            .where(PlaylistTrack.spotify_track_id == song.spotify_track_id)
            .order_by(Playlist.name)
        ).all() if song.spotify_track_id else []

        db.execute(
            text(
                """
                INSERT INTO library_search (
                    song_id, title, artist, album, genre, playlist, filename,
                    spotify_id, musicbrainz_id, isrc
                ) VALUES (
                    :song_id, :title, :artist, :album, :genre, :playlist,
                    :filename, :spotify_id, :musicbrainz_id, :isrc
                )
                """
            ),
            {
                "song_id": song.id,
                "title": song.title or "",
                "artist": song.artist or "",
                "album": song.album or "",
                "genre": song.genre or "",
                "playlist": " ".join(playlists),
                "filename": song.filename or "",
                "spotify_id": song.spotify_track_id or "",
                "musicbrainz_id": song.musicbrainz_recording_id or "",
                "isrc": song.isrc or "",
            },
        )

    def index_spotify_tracks(self, db: Session, spotify_track_ids: set[str]) -> None:
        if not spotify_track_ids:
            return
        song_ids = db.scalars(
            select(Song.id).where(Song.spotify_track_id.in_(spotify_track_ids))
        ).all()
        for song_id in song_ids:
            self.index_song(db, song_id)

    def rebuild(self, db: Session) -> int:
        self.ensure_schema(db)
        db.execute(text("DELETE FROM library_search"))
        song_ids = db.scalars(select(Song.id).order_by(Song.id)).all()
        for song_id in song_ids:
            self.index_song(db, song_id)
        return len(song_ids)

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
