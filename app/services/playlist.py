from app.core.logging import logger
from app.downloaders.spotdl import SpotDLClient
from app.services.spotify.metadata import resolve_playlist

# Initialize the SpotDL client to keep it ready as a fallback
spotdl_client = SpotDLClient()

def import_playlist(url: str):
    """
    Import a playlist using a smart fallback mechanism.
    
    1. Attempts to use the official Spotify API for rich metadata and speed.
    2. If Spotify blocks the request (e.g., restricted editorial playlists),
       it catches the error and falls back to SpotDL's internal scraper.
    """
    try:
        logger.info("Attempting to fetch playlist metadata via Official Spotify API...")
        # Try the fast, official route first
        return resolve_playlist(url)
        
    except Exception as ex:
        logger.warning(
            "Official API request blocked or failed: {}. "
            "Falling back to SpotDL scraper...", 
            ex
        )
        # Execute the fallback to SpotDL's web scraper
        return spotdl_client.playlist(url)
