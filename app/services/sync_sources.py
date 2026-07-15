from sqlalchemy.orm import Session

from app.database.crud_sync_sources import (
    create_sync_source,
    get_sync_source_by_spotify_id,
)
# Use the robust import engine that includes the SpotDL fallback
from app.services.playlist import import_playlist
from app.services.spotify.url import spotify_resource

def create_playlist_source(
    db: Session,
    spotify_url: str,
):
    resource, spotify_id = spotify_resource(spotify_url)
    
    if resource != "playlist":
        raise ValueError("Only Spotify playlists are supported.")

    existing = get_sync_source_by_spotify_id(
        db,
        spotify_id,
    )
    if existing:
        return existing

    # This will now gracefully fall back to SpotDL if the Spotify API 404s
    playlist = import_playlist(spotify_url)

    return create_sync_source(
        db=db,
        type="playlist",
        spotify_id=spotify_id,
        spotify_url=spotify_url,
        name=playlist.name,
    )
