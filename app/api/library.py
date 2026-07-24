import json
from queue import Empty

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, select
from app.database.session import SessionLocal, get_db
from app.database.models import Song
from app.services.artwork import artwork_url
from app.services.library_service import index_library_file, rescan_library
from app.services.library_events import library_events
from app.services.library_search import SearchFilters, SearchQueryError, library_search
from app.services.library_filters import (
    LibraryFilters,
    apply_song_filters,
    apply_song_sort,
)
from app.services.collections import collection_engine
from app.services.library_analytics import library_analytics
from app.services.duplicate_detector import TIERS, duplicate_detector
from app.services.library_catalog import (
    playlist_sources_for_tracks,
    serialize_song,
    serialize_song_page,
    with_song_artwork,
)
from app.api.schemas.library import (
    AlbumProjectionResponse,
    ArtistProjectionResponse,
    SearchPageResponse,
    SongResponse,
)

router = APIRouter(
    prefix="/api/library",
    tags=["library"],
)


class IndexFileRequest(BaseModel):
    path: str
    force: bool = False
    download_source: str | None = None


@router.get("/analytics", summary="Get Library analytics")
def get_library_analytics(db: Session = Depends(get_db)):
    return library_analytics.calculate(db)


@router.get("/duplicates", summary="List explainable duplicate candidate groups")
def list_duplicates(
    db: Session = Depends(get_db),
    tier: str | None = Query(default=None),
    include_missing: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    if tier is not None and tier not in TIERS:
        raise HTTPException(status_code=400, detail="Unsupported duplicate tier")
    return duplicate_detector.list(
        db, tier=tier, include_missing=include_missing, limit=limit, offset=offset
    )


@router.get("/duplicates/{group_id}", summary="Compare one duplicate candidate group")
def get_duplicate_group(
    group_id: str,
    include_missing: bool = False,
    db: Session = Depends(get_db),
):
    group = duplicate_detector.get(db, group_id, include_missing=include_missing)
    if group is None:
        raise HTTPException(status_code=404, detail="Duplicate group not found")
    return group


_playlist_sources = playlist_sources_for_tracks
_serialize_song = serialize_song


@router.get("/songs", response_model=list[SongResponse], summary="List indexed Songs")
def list_songs(
    db: Session = Depends(get_db),
    sort_by: str = "artist",
    artist: str | None = None,
    album: str | None = None,
    genre: str | None = None,
    codec: str | None = None,
    playlist_id: int | None = Query(default=None, ge=1),
    year: int | None = Query(default=None, ge=0),
    min_bitrate: int | None = Query(default=None, ge=0),
    max_bitrate: int | None = Query(default=None, ge=0),
    downloaded_today: bool = False,
    recently_added: bool = False,
    missing_artwork: bool = False,
    missing_metadata: bool = False,
    include_missing: bool = False,
    limit: int | None = Query(default=None, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    filters = LibraryFilters(
        artist=artist,
        album=album,
        genre=genre,
        codec=codec,
        playlist_id=playlist_id,
        year=year,
        min_bitrate=min_bitrate,
        max_bitrate=max_bitrate,
        downloaded_today=downloaded_today,
        recently_added=recently_added,
        missing_artwork=missing_artwork,
        missing_metadata=missing_metadata,
        include_missing=include_missing,
    )
    normalized_sort = "recently_added" if sort_by == "newest" else sort_by
    query = with_song_artwork(
        apply_song_sort(
            apply_song_filters(select(Song), filters),
            normalized_sort,
        )
    )
    if offset:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    songs = db.scalars(query).all()
    return serialize_song_page(db, songs)


@router.get(
    "/search",
    response_model=SearchPageResponse,
    summary="Search the Library Index",
    description="Runs an FTS5 search without filesystem access and returns a bounded result page.",
)
def search_library(
    q: str = Query(min_length=1, max_length=200),
    db: Session = Depends(get_db),
    artist: str | None = None,
    album: str | None = None,
    genre: str | None = None,
    codec: str | None = None,
    playlist_id: int | None = Query(default=None, ge=1),
    year: int | None = Query(default=None, ge=0),
    min_bitrate: int | None = Query(default=None, ge=0),
    max_bitrate: int | None = Query(default=None, ge=0),
    downloaded_today: bool = False,
    recently_added: bool = False,
    missing_artwork: bool = False,
    missing_metadata: bool = False,
    include_missing: bool = False,
    sort_by: str = "relevance",
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    try:
        page = library_search.search(
            db,
            q,
            filters=SearchFilters(
                artist=artist,
                album=album,
                genre=genre,
                codec=codec,
                playlist_id=playlist_id,
                year=year,
                min_bitrate=min_bitrate,
                max_bitrate=max_bitrate,
                downloaded_today=downloaded_today,
                recently_added=recently_added,
                missing_artwork=missing_artwork,
                missing_metadata=missing_metadata,
                include_missing=include_missing,
            ),
            sort_by=sort_by,
            limit=limit,
            offset=offset,
        )
    except SearchQueryError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    songs = db.scalars(
        with_song_artwork(select(Song).where(Song.id.in_(page.song_ids)))
    ).all()
    songs_by_id = {song.id: song for song in songs}
    ordered = [songs_by_id[song_id] for song_id in page.song_ids if song_id in songs_by_id]
    return {
        "query": q,
        "items": serialize_song_page(db, ordered),
        "total": page.total,
        "limit": limit,
        "offset": offset,
        "filters": {
            "artist": artist,
            "album": album,
            "genre": genre,
            "codec": codec,
            "playlist_id": playlist_id,
            "year": year,
            "min_bitrate": min_bitrate,
            "max_bitrate": max_bitrate,
            "downloaded_today": downloaded_today,
            "recently_added": recently_added,
            "missing_artwork": missing_artwork,
            "missing_metadata": missing_metadata,
            "include_missing": include_missing,
        },
    }


@router.get("/filter-options", summary="List indexed filter values")
def library_filter_options(db: Session = Depends(get_db)):
    available = Song.availability_status == "available"

    def values(column):
        return list(
            db.scalars(
                select(column)
                .where(available, column.is_not(None), column != "")
                .distinct()
                .order_by(func.lower(column))
            ).all()
        )

    return {
        "artists": values(Song.artist),
        "albums": values(Song.album),
        "genres": values(Song.genre),
        "codecs": values(Song.codec),
        "bitrate_ranges": [
            {"id": "lossless", "label": "Lossless / 900+ kbps", "min": 900000, "max": None},
            {"id": "high", "label": "320+ kbps", "min": 320000, "max": None},
            {"id": "standard", "label": "192–319 kbps", "min": 192000, "max": 319999},
            {"id": "compact", "label": "Up to 191 kbps", "min": None, "max": 191999},
        ],
    }


@router.post("/search/rebuild", summary="Rebuild the derived search projection")
def rebuild_search(db: Session = Depends(get_db)):
    indexed = library_search.rebuild(db)
    db.commit()
    return {"status": "ok", "indexed": indexed}


@router.get("/events", summary="Stream transient Library events")
def stream_library_events():
    subscriber = library_events.subscribe()

    def event_stream():
        try:
            while True:
                try:
                    event = subscriber.get(timeout=15)
                    payload = json.dumps(event.to_dict(), ensure_ascii=False)
                    yield (
                        f"id: {event.id}\n"
                        f"event: {event.type}\n"
                        f"data: {payload}\n\n"
                    )
                except Empty:
                    yield ": keep-alive\n\n"
        finally:
            library_events.unsubscribe(subscriber)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/songs/{song_id}", response_model=SongResponse, summary="Get one indexed Song")
def get_song(song_id: int, db: Session = Depends(get_db)):
    song = db.get(Song, song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="Song not found")

    sources = playlist_sources_for_tracks(
        db,
        {song.spotify_track_id} if song.spotify_track_id else set(),
    )
    return serialize_song(song, sources.get(song.spotify_track_id or "", []))


@router.get(
    "/albums",
    response_model=list[AlbumProjectionResponse],
    summary="List indexed album projections",
)
def list_albums(
    db: Session = Depends(get_db),
    limit: int | None = Query(default=None, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """Group songs by album to power the Albums view mode."""
    statement = (
        select(
            Song.album,
            Song.album_artist,
            func.max(Song.artist).label("artist"),
            func.max(Song.cover_url).label("cover_url"),
            func.max(Song.artwork_id).label("artwork_id"),
            func.count(Song.id).label("track_count"),
            func.sum(Song.duration).label("total_duration"),
        )
        .where(Song.availability_status == "available")
        .group_by(Song.album, Song.album_artist)
        .order_by(Song.album.asc())
    )
    if offset:
        statement = statement.offset(offset)
    if limit is not None:
        statement = statement.limit(limit)
    albums_query = db.execute(statement).all()
    
    return [
        {
            "album": a.album or "Unknown Album",
            "artist": a.album_artist or a.artist or "Unknown Artist",
            "cover_url": artwork_url(a.artwork_id) or a.cover_url,
            "track_count": a.track_count,
            "total_duration": round(a.total_duration / 60, 1) if a.total_duration else 0,
        }
        for a in albums_query
    ]


@router.get(
    "/artists",
    response_model=list[ArtistProjectionResponse],
    summary="List indexed artist projections",
)
def list_artists(
    db: Session = Depends(get_db),
    limit: int | None = Query(default=None, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """Group songs by artist to power the Artists view mode."""
    statement = (
        select(
            Song.artist,
            func.count(Song.id).label("song_count"),
            func.count(func.distinct(Song.album)).label("album_count"),
            func.max(Song.cover_url).label("cover_url"),
            func.max(Song.artwork_id).label("artwork_id"),
        )
        .where(Song.availability_status == "available")
        .group_by(Song.artist)
        .order_by(Song.artist.asc())
    )
    if offset:
        statement = statement.offset(offset)
    if limit is not None:
        statement = statement.limit(limit)
    artists_query = db.execute(statement).all()
    
    return [
        {
            "artist": art.artist or "Unknown Artist",
            "song_count": art.song_count,
            "album_count": art.album_count,
            "cover_url": artwork_url(art.artwork_id) or art.cover_url,
        }
        for art in artists_query
    ]


@router.get("/collections", summary="List Smart Collection definitions and counts")
def list_collections(db: Session = Depends(get_db)):
    return collection_engine.summaries(db)


@router.get("/collections/{collection_id}", summary="Get a Smart Collection definition")
def get_collection(collection_id: str, db: Session = Depends(get_db)):
    definition = collection_engine.get(collection_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return definition.to_dict(song_count=collection_engine.count(db, collection_id))


@router.get("/collections/{collection_id}/songs", summary="List Songs in a Smart Collection")
def get_collection_songs(
    collection_id: str,
    db: Session = Depends(get_db),
    sort_by: str = "artist",
    artist: str | None = None,
    album: str | None = None,
    genre: str | None = None,
    codec: str | None = None,
    min_bitrate: int | None = Query(default=None, ge=0),
    max_bitrate: int | None = Query(default=None, ge=0),
    downloaded_today: bool = False,
    recently_added: bool = False,
    missing_artwork: bool = False,
    missing_metadata: bool = False,
    limit: int | None = Query(default=None, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    definition = collection_engine.get(collection_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    filters = LibraryFilters(
        artist=artist,
        album=album,
        genre=genre,
        codec=codec,
        min_bitrate=min_bitrate,
        max_bitrate=max_bitrate,
        downloaded_today=downloaded_today,
        recently_added=recently_added,
        missing_artwork=missing_artwork,
        missing_metadata=missing_metadata,
    )
    statement = collection_engine.statement(
        collection_id,
        filters=filters,
        sort_by=sort_by,
    )
    total = db.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    ) or 0
    if offset:
        statement = statement.offset(offset)
    if limit is not None:
        statement = statement.limit(limit)
    songs = db.scalars(with_song_artwork(statement)).all()
    return {
        "collection": definition.to_dict(song_count=total),
        "items": serialize_song_page(db, songs),
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/genres", summary="List indexed genres")
def list_genres(db: Session = Depends(get_db)):
    """Retrieve available genres for filtering."""
    genres = db.scalars(
        select(Song.genre)
        .where(
            Song.genre.is_not(None),
            Song.availability_status == "available",
        )
        .distinct()
    ).all()
    return sorted(genre for genre in genres if genre)


@router.get(
    "/missing",
    response_model=list[SongResponse],
    summary="List retained missing-file records",
)
def list_missing_files(
    db: Session = Depends(get_db),
    limit: int | None = Query(default=None, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    statement = (
        select(Song)
        .where(Song.availability_status == "missing")
        .order_by(Song.path)
    )
    if offset:
        statement = statement.offset(offset)
    if limit is not None:
        statement = statement.limit(limit)
    songs = db.scalars(with_song_artwork(statement)).all()
    return serialize_song_page(db, songs)


@router.post("/index", summary="Incrementally index one managed file")
def index_file(request: IndexFileRequest, db: Session = Depends(get_db)):
    try:
        result = index_library_file(
            db,
            request.path,
            force=request.force,
            download_source=request.download_source,
        )
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return {
        "path": result.path,
        "status": result.status,
        "song_id": result.song_id,
        "error": result.error,
    }


@router.delete("/song/{song_id}", summary="Delete one Song file")
def delete_song(song_id: int, db: Session = Depends(get_db)):
    song = db.get(Song, song_id)
    if song:
        from app.services.library_service import managed_library_path

        try:
            path = managed_library_path(song.path)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if path.exists():
            try:
                path.unlink()
            except OSError as error:
                raise HTTPException(status_code=409, detail=f"Could not delete song file: {error}") from error
        song.availability_status = "missing"
        db.commit()
        library_search.index_song(db, song_id)
        db.commit()
    return {"status": "success"}


@router.post("/rescan", summary="Reconcile the configured music folder")
def rescan(force: bool = False):
    db = SessionLocal()
    try:
        result = rescan_library(db, force=force)
        return {"status": "ok", **result.to_dict()}
    finally:
        db.close()


@router.post("/reindex", summary="Force a complete Library re-index")
def reindex():
    db = SessionLocal()
    try:
        result = rescan_library(db, force=True)
        return {"status": "ok", **result.to_dict()}
    finally:
        db.close()
