from app.services.spotify.metadata import resolve_playlist_details


def import_playlist(url: str):
    return resolve_playlist_details(url)
