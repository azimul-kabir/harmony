import urllib.parse
from sqlalchemy.orm import Session
from app.services.settings_service import get_settings_by_category

def _get_base_url(db: Session) -> str | None:
    settings = get_settings_by_category(db, "navidrome")
    if not settings.get("navidrome_connected"):
        return None
    url = settings.get("navidrome_url", "")
    return url.rstrip('/') if url else None

def get_artist_link(db: Session, artist_name: str, artist_id: str | None = None) -> str | None:
    base = _get_base_url(db)
    if not base:
        return None
    # Assuming search fallback for now if we don't have exact navidrome IDs
    # (Since Harmony tracks Spotify metadata, we don't strictly have Navidrome's internal integer IDs)
    query = urllib.parse.quote(artist_name)
    return f"{base}/app/#/search?q={query}"

def get_album_link(db: Session, album_name: str, album_id: str | None = None) -> str | None:
    base = _get_base_url(db)
    if not base:
        return None
    query = urllib.parse.quote(album_name)
    return f"{base}/app/#/search?q={query}"

def get_song_link(db: Session, song_title: str, artist_name: str) -> str | None:
    base = _get_base_url(db)
    if not base:
        return None
    query = urllib.parse.quote(f"{song_title} {artist_name}")
    return f"{base}/app/#/search?q={query}"

def get_playlist_link(db: Session, playlist_name: str) -> str | None:
    base = _get_base_url(db)
    if not base:
        return None
    # Navidrome Playlists URL
    return f"{base}/app/#/playlists"
