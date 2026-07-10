from functools import lru_cache

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from app.core.config import get_settings

settings = get_settings()


@lru_cache(maxsize=1)
def get_client() -> spotipy.Spotify:
    auth = SpotifyClientCredentials(
        client_id=settings.spotify_client_id,
        client_secret=settings.spotify_client_secret,
    )

    return spotipy.Spotify(auth_manager=auth)