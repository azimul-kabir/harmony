import os
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database.session import SessionLocal, get_db
from app.database.models import Song
from app.services.library_scanner import scan_library

router = APIRouter(
    prefix="/api/library",
    tags=["library"],
)

@router.get("/songs")
def list_songs(
    db: Session = Depends(get_db),
    sort_by: str = "artist",
    genre: str | None = None,
):
    query = db.query(Song)
    
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
    return [
        {
            "id": s.id,
            "title": s.title,
            "artist": s.artist,
            "album": s.album,
            "album_artist": s.album_artist,
            "genre": s.genre,
            "year": s.year,
            "duration": s.duration,
            "filename": s.filename,
            "path": s.path,
            "cover_url": s.cover_url
        }
        for s in songs
    ]


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
    genres = db.query(Song.genre).filter(Song.genre != None).distinct().all()
    return sorted([g[0] for g in genres if g[0]])


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
def rescan():
    db = SessionLocal()
    try:
        scan_library(db)
        return {"status": "ok"}
    finally:
        db.close()
