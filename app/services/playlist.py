from app.services.spotify.metadata import resolve_playlist

def import_playlist(url: str):
    """
    Import a playlist using the official Spotify API resolver.
    This fetches rich metadata and supports large editorial playlists.
    """
    return resolve_playlist(url)
