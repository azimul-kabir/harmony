from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Select, func, select

from app.database.models import PlaylistTrack, Song
from app.services.library_predicates import missing_metadata_expression
from app.core.time import utcnow_naive


RECENT_DAYS = 7


@dataclass(frozen=True, slots=True)
class LibraryFilters:
    artist: str | None = None
    album: str | None = None
    genre: str | None = None
    codec: str | None = None
    playlist_id: int | None = None
    year: int | None = None
    min_bitrate: int | None = None
    max_bitrate: int | None = None
    downloaded_today: bool = False
    recently_added: bool = False
    missing_artwork: bool = False
    missing_metadata: bool = False
    include_missing: bool = False


def utc_day_start() -> datetime:
    return utcnow_naive().replace(hour=0, minute=0, second=0, microsecond=0)


def recent_cutoff() -> datetime:
    return utcnow_naive() - timedelta(days=RECENT_DAYS)


def apply_song_filters(statement: Select, filters: LibraryFilters) -> Select:
    if not filters.include_missing:
        statement = statement.where(Song.availability_status == "available")
    for field in ("artist", "album", "genre", "codec"):
        value = getattr(filters, field)
        if value:
            statement = statement.where(
                func.lower(getattr(Song, field)) == value.lower()
            )
    if filters.year is not None:
        statement = statement.where(Song.year == filters.year)
    if filters.min_bitrate is not None:
        statement = statement.where(Song.bitrate >= filters.min_bitrate)
    if filters.max_bitrate is not None:
        statement = statement.where(Song.bitrate <= filters.max_bitrate)
    if filters.downloaded_today:
        statement = statement.where(Song.created_at >= utc_day_start())
    if filters.recently_added:
        statement = statement.where(Song.created_at >= recent_cutoff())
    if filters.missing_artwork:
        statement = statement.where(Song.artwork_status == "missing")
    if filters.missing_metadata:
        statement = statement.where(missing_metadata_expression())
    if filters.playlist_id is not None:
        statement = statement.where(
            select(PlaylistTrack.spotify_track_id).where(
                PlaylistTrack.playlist_id == filters.playlist_id,
                PlaylistTrack.spotify_track_id == Song.spotify_track_id,
            ).exists()
        )
    return statement


def apply_song_sort(statement: Select, sort_by: str) -> Select:
    normalized = sort_by.casefold()
    orders = {
        "artist": (func.lower(Song.artist), func.lower(Song.album), Song.disc, Song.track),
        "album": (func.lower(Song.album), func.lower(Song.artist), Song.disc, Song.track),
        "title": (func.lower(Song.title), func.lower(Song.artist)),
        "alphabetical": (
            func.lower(func.coalesce(Song.title, Song.filename)),
            func.lower(Song.artist),
        ),
        "recently_added": (Song.created_at.desc(), Song.id.desc()),
        "recently_modified": (Song.last_modified.desc(), Song.id.desc()),
        "bitrate": (Song.bitrate.desc(), func.lower(Song.title)),
        "duration": (Song.duration.desc(), func.lower(Song.title)),
        "year": (Song.year.desc(), func.lower(Song.album), Song.track),
    }
    return statement.order_by(*orders.get(normalized, orders["artist"]))


def raw_filter_clauses(filters: LibraryFilters) -> tuple[list[str], dict[str, object]]:
    clauses: list[str] = []
    parameters: dict[str, object] = {}
    if not filters.include_missing:
        clauses.append("songs.availability_status = 'available'")
    for field in ("artist", "album", "genre", "codec"):
        value = getattr(filters, field)
        if value:
            clauses.append(f"lower(songs.{field}) = lower(:{field})")
            parameters[field] = value
    for field in ("year", "min_bitrate", "max_bitrate"):
        value = getattr(filters, field)
        if value is not None:
            operator = {"year": "=", "min_bitrate": ">=", "max_bitrate": "<="}[field]
            column = "bitrate" if "bitrate" in field else field
            clauses.append(f"songs.{column} {operator} :{field}")
            parameters[field] = value
    if filters.downloaded_today:
        clauses.append("songs.created_at >= :downloaded_today")
        parameters["downloaded_today"] = utc_day_start()
    if filters.recently_added:
        clauses.append("songs.created_at >= :recently_added")
        parameters["recently_added"] = recent_cutoff()
    if filters.missing_artwork:
        clauses.append("songs.artwork_status = 'missing'")
    if filters.missing_metadata:
        clauses.append(
            "(coalesce(songs.title, '') = '' OR coalesce(songs.artist, '') = '' "
            "OR coalesce(songs.album, '') = '')"
        )
    if filters.playlist_id is not None:
        clauses.append(
            """EXISTS (
                SELECT 1 FROM playlist_tracks
                WHERE playlist_tracks.playlist_id = :playlist_id
                AND playlist_tracks.spotify_track_id = songs.spotify_track_id
            )"""
        )
        parameters["playlist_id"] = filters.playlist_id
    return clauses, parameters


def raw_sort_clause(sort_by: str, *, relevance_default: bool = False) -> str:
    orders = {
        "artist": "lower(songs.artist), lower(songs.album), songs.disc, songs.track",
        "album": "lower(songs.album), lower(songs.artist), songs.disc, songs.track",
        "title": "lower(songs.title), lower(songs.artist)",
        "alphabetical": "lower(coalesce(songs.title, songs.filename)), lower(songs.artist)",
        "recently_added": "songs.created_at DESC, songs.id DESC",
        "recently_modified": "songs.last_modified DESC, songs.id DESC",
        "bitrate": "songs.bitrate DESC, lower(songs.title)",
        "duration": "songs.duration DESC, lower(songs.title)",
        "year": "songs.year DESC, lower(songs.album), songs.track",
    }
    fallback = "bm25(library_search), lower(songs.artist), lower(songs.album)" if relevance_default else orders["artist"]
    return orders.get(sort_by.casefold(), fallback)
