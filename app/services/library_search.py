from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

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
MAX_QUERY_TERMS = 20
MAX_DUPLICATE_FILTER_SONGS = 800
FIELD_ALIASES = {
    "title": "title", "artist": "artist", "album": "album", "genre": "genre",
    "playlist": "playlist", "filename": "filename", "file": "filename",
    "spotify": "spotify_id", "spotify_id": "spotify_id",
    "musicbrainz": "musicbrainz_id", "mbid": "musicbrainz_id",
    "musicbrainz_id": "musicbrainz_id", "isrc": "isrc",
}
CONTROL_VALUES = {
    ("has", "issues"), ("is", "duplicate"), ("is", "missing"),
    ("is", "available"), ("missing", "artwork"), ("missing", "metadata"),
    ("has", "artwork"),
}

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


@dataclass(frozen=True, slots=True)
class ParsedSearch:
    expression: str | None
    exclusions: tuple[str, ...]
    controls: frozenset[tuple[str, str]]
    advanced: bool


class SearchQueryError(ValueError):
    pass


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
        parsed = _parse_search(query)
        if not parsed.expression and not parsed.exclusions and not parsed.controls:
            return SearchPage(song_ids=[], total=0)

        filters = filters or SearchFilters()
        filter_clauses, filter_parameters = raw_filter_clauses(filters)
        if ("is", "missing") in parsed.controls and not filters.include_missing:
            filter_clauses = [
                clause for clause in filter_clauses
                if clause != "songs.availability_status = 'available'"
            ]
        clauses = list(filter_clauses)
        parameters: dict[str, object] = dict(filter_parameters)
        if parsed.expression:
            clauses.insert(0, "library_search MATCH :query")
            parameters["query"] = parsed.expression
        for index, exclusion in enumerate(parsed.exclusions):
            name = f"exclude_{index}"
            clauses.append(
                f"""songs.id NOT IN (
                    SELECT song_id FROM library_search
                    WHERE library_search MATCH :{name}
                )"""
            )
            parameters[name] = exclusion
        control_clauses, control_parameters = self._control_clauses(db, parsed.controls)
        clauses.extend(control_clauses)
        parameters.update(control_parameters)

        where = " AND ".join(clauses) if clauses else "1 = 1"
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
                ORDER BY {raw_sort_clause(sort_by, relevance_default=bool(parsed.expression))}
                LIMIT :limit OFFSET :offset"""
            ),
            {**parameters, "limit": limit, "offset": offset},
        ).all()
        return SearchPage(song_ids=[row[0] for row in rows], total=total)

    def _control_clauses(
        self, db: Session, controls: frozenset[tuple[str, str]]
    ) -> tuple[list[str], dict[str, Any]]:
        clauses: list[str] = []
        parameters: dict[str, Any] = {}
        if ("has", "issues") in controls:
            clauses.append(
                """EXISTS (
                    SELECT 1 FROM metadata_issues
                    WHERE metadata_issues.song_id = songs.id
                    AND metadata_issues.status = 'open'
                )"""
            )
        if ("missing", "artwork") in controls:
            clauses.append("songs.artwork_status = 'missing'")
        if ("has", "artwork") in controls:
            clauses.append("songs.artwork_id IS NOT NULL")
        if ("missing", "metadata") in controls:
            clauses.append(
                "(coalesce(songs.title, '') = '' OR coalesce(songs.artist, '') = '' "
                "OR coalesce(songs.album, '') = '')"
            )
        if ("is", "missing") in controls:
            clauses.append("songs.availability_status = 'missing'")
        if ("is", "available") in controls:
            clauses.append("songs.availability_status = 'available'")
        if ("is", "duplicate") in controls:
            from app.services.duplicate_detector import duplicate_detector
            song_ids = sorted({
                song_id
                for group in duplicate_detector.detect(db, include_missing=True)
                for song_id in group["song_ids"]
            })
            if len(song_ids) > MAX_DUPLICATE_FILTER_SONGS:
                raise SearchQueryError("Duplicate-filter scope exceeds the safe search limit.")
            if not song_ids:
                clauses.append("1 = 0")
            else:
                names = []
                for index, song_id in enumerate(song_ids):
                    name = f"duplicate_song_{index}"
                    names.append(f":{name}")
                    parameters[name] = song_id
                clauses.append(f"songs.id IN ({', '.join(names)})")
        return clauses, parameters


def _fts_expression(query: str) -> str:
    return _parse_search(query).expression or ""


def _term_expression(value: str, field: str | None, *, phrase: bool) -> str | None:
    tokens = re.findall(r"[^\W_]+", value, flags=re.UNICODE)
    if not tokens:
        return None
    prefix = f"{field}:" if field else ""
    if phrase and len(tokens) > 1:
        escaped = " ".join(token.replace('"', '""') for token in tokens)
        return f'{prefix}"{escaped}"'
    expressions = [
        f'{prefix}"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens
    ]
    return expressions[0] if len(expressions) == 1 else f"({' AND '.join(expressions)})"


def _parse_search(query: str) -> ParsedSearch:
    if query.count('"') % 2:
        raise SearchQueryError("Search contains an unmatched quote.")
    pattern = re.compile(
        r'(?P<negative>-)?(?:(?P<field>[A-Za-z_]+):)?'
        r'(?P<value>"[^"]*"|[^\s]+)'
    )
    includes: list[str] = []
    exclusions: list[str] = []
    controls: set[tuple[str, str]] = set()
    advanced = False
    matches = list(pattern.finditer(query))
    if len(matches) > MAX_QUERY_TERMS:
        raise SearchQueryError(f"Search supports at most {MAX_QUERY_TERMS} terms.")
    for match in matches:
        negative = bool(match.group("negative"))
        raw_field = match.group("field")
        raw_value = match.group("value")
        phrase = raw_value.startswith('"')
        value = raw_value[1:-1] if phrase else raw_value
        field = raw_field.casefold() if raw_field else None
        if field in {"has", "is", "missing"}:
            control = (field, value.casefold())
            if negative or control not in CONTROL_VALUES:
                raise SearchQueryError(f"Unsupported search filter: {field}:{value}")
            controls.add(control)
            advanced = True
            continue
        fts_field = None
        if field:
            fts_field = FIELD_ALIASES.get(field)
            if fts_field is None:
                raise SearchQueryError(f"Unsupported search field: {field}")
            advanced = True
        if negative:
            advanced = True
        expression = _term_expression(value, fts_field, phrase=phrase)
        if expression:
            (exclusions if negative else includes).append(expression)
    return ParsedSearch(
        expression=" AND ".join(includes) or None,
        exclusions=tuple(exclusions),
        controls=frozenset(controls),
        advanced=advanced,
    )


library_search = LibrarySearchService()
