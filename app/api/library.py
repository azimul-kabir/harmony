import os
import json
from queue import Empty

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, select
from app.database.session import SessionLocal, get_db
from app.database.models import Playlist, PlaylistTrack, Song
from app.services.library_service import index_library_file, rescan_library
from app.services.library_events import library_events

router = APIRouter(
    prefix="/api/library",
    tags=["library"],
)


class IndexFileRequest(BaseModel):
    path: str
    force: bool = False
    download_source: str | None = None


def _playlist_sources(db: Session, spotify_track_ids: set[str]) -> dict[str, list[dict]]:
    if not spotify_track_ids:
        return {}

    rows = db.execute(
        select(
            PlaylistTrack.spotify_track_id,
            Playlist.id,
            Playlist.name,
            Playlist.spotify_id,
        )
        .join(Playlist, Playlist.id == PlaylistTrack.playlist_id)
        .where(PlaylistTrack.spotify_track_id.in_(spotify_track_ids))
        .order_by(Playlist.name)
    ).all()

    sources: dict[str, list[dict]] = {}
    for spotify_track_id, playlist_id, name, spotify_id in rows:
        sources.setdefault(spotify_track_id, []).append(
            {"id": playlist_id, "name": name, "spotify_id": spotify_id}
        )
    return sources


def _serialize_song(song: Song, playlist_sources: list[dict] | None = None) -> dict:
    return {
        "id": song.id,
        "path": song.path,
        "filename": song.filename,
        "artist": song.artist,
        "album": song.album,
        "album_artist": song.album_artist,
        "title": song.title,
        "track_number": song.track,
        "disc_number": song.disc,
        # Compatibility fields used by the current UI and API clients.
        "track": song.track,
        "disc": song.disc,
        "genre": song.genre,
        "year": song.year,
        "duration": song.duration,
        "bitrate": song.bitrate,
        "codec": song.codec,
        "sample_rate": song.sample_rate,
        "file_size": song.file_size,
        "artwork_status": song.artwork_status,
        "cover_url": song.cover_url,
        "date_added": song.created_at,
        "last_modified": song.last_modified,
        "last_indexed_at": song.last_indexed_at,
        "availability_status": song.availability_status,
        "spotify_track_id": song.spotify_track_id,
        "musicbrainz_recording_id": song.musicbrainz_recording_id,
        "isrc": song.isrc,
        "download_source": song.download_source,
        "playlist_sources": playlist_sources or [],
    }

@router.get("/songs")
def list_songs(
    db: Session = Depends(get_db),
    sort_by: str = "artist",
    genre: str | None = None,
    include_missing: bool = False,
):
    query = db.query(Song)

    if not include_missing:
        query = query.filter(Song.availability_status == "available")
    
    if genre:
        query = query.filter(func.lower(Song.genre) == genre.lower())
        
    # Safe Sorting logic
    if sort_by == "title":
        query = query.order_by(Song.title.asc())
    elif sort_by == "album":
        query = query.order_by(Song.album.asc(), Song.track.asc())
    elif sort_by == "newest":
        query = query.order_by(Song.created_at.desc())
    elif sort_by == "duration":
        query = query.order_by(Song.duration.desc())
    elif sort_by == "year":
        query = query.order_by(Song.year.desc())
    else:
        query = query.order_by(Song.artist.asc(), Song.album.asc(), Song.track.asc())

    songs = query.all()
    source_map = _playlist_sources(
        db,
        {song.spotify_track_id for song in songs if song.spotify_track_id},
    )
    return [
        _serialize_song(song, source_map.get(song.spotify_track_id or "", []))
        for song in songs
    ]


@router.get("/events")
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


@router.get("/songs/{song_id}")
def get_song(song_id: int, db: Session = Depends(get_db)):
    song = db.get(Song, song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="Song not found")

    sources = _playlist_sources(
        db,
        {song.spotify_track_id} if song.spotify_track_id else set(),
    )
    return _serialize_song(song, sources.get(song.spotify_track_id or "", []))


@router.get("/albums")
def list_albums(db: Session = Depends(get_db)):
    """Group songs by album to power the Albums view mode."""
    albums_query = (
        db.query(
            Song.album,
            Song.album_artist,
            Song.artist,
            Song.cover_url,
            func.count(Song.id).label("track_count"),
            func.sum(Song.duration).label("total_duration")
        )
        .filter(Song.availability_status == "available")
        .group_by(Song.album, Song.album_artist)
        .order_by(Song.album.asc())
        .all()
    )
    
    return [
        {
            "album": a.album or "Unknown Album",
            "artist": a.album_artist or a.artist or "Unknown Artist",
            "cover_url": a.cover_url,
            "track_count": a.track_count,
            "total_duration": round(a.total_duration / 60, 1) if a.total_duration else 0
        }
        for a in albums_query
    ]


@router.get("/artists")
def list_artists(db: Session = Depends(get_db)):
    """Group songs by artist to power the Artists view mode."""
    artists_query = (
        db.query(
            Song.artist,
            func.count(Song.id).label("song_count"),
            func.count(func.distinct(Song.album)).label("album_count"),
            func.max(Song.cover_url).label("cover_url")
        )
        .filter(Song.availability_status == "available")
        .group_by(Song.artist)
        .order_by(Song.artist.asc())
        .all()
    )
    
    return [
        {
            "artist": art.artist or "Unknown Artist",
            "song_count": art.song_count,
            "album_count": art.album_count,
            "cover_url": art.cover_url
        }
        for art in artists_query
    ]


@router.get("/genres")
def list_genres(db: Session = Depends(get_db)):
    """Retrieve available genres for filtering."""
    genres = (
        db.query(Song.genre)
        .filter(
            Song.genre != None,
            Song.availability_status == "available",
        )
        .distinct()
        .all()
    )
    return sorted([g[0] for g in genres if g[0]])


@router.get("/missing")
def list_missing_files(db: Session = Depends(get_db)):
    songs = db.scalars(
        select(Song)
        .where(Song.availability_status == "missing")
        .order_by(Song.path)
    ).all()
    return [_serialize_song(song) for song in songs]


@router.post("/index")
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


@router.delete("/song/{song_id}")
def delete_song(song_id: int, db: Session = Depends(get_db)):
    song = db.get(Song, song_id)
    if song:
        if os.path.exists(song.path):
            try:
                os.remove(song.path)
            except OSError:
                pass
        db.delete(song)
        db.commit()
    return {"status": "success"}


@router.post("/rescan")
def rescan(force: bool = False):
    db = SessionLocal()
    try:
        result = rescan_library(db, force=force)
        return {"status": "ok", **result.to_dict()}
    finally:
        db.close()


@router.post("/reindex")
def reindex():
    db = SessionLocal()
    try:
        result = rescan_library(db, force=True)
        return {"status": "ok", **result.to_dict()}
    finally:
        db.close()
