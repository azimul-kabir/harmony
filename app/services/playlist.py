from app.core.logging import logger
from app.downloaders.spotdl import SpotDLClient

# Initialize the SpotDL client
spotdl_client = SpotDLClient()

def import_playlist(url: str):
    """
    Import a playlist using SpotDL directly.
    Bypasses the Official Spotify API entirely for playlists to avoid 
    401 Unauthorized errors on collaborative or restricted public playlists.
    """
    logger.info("Fetching playlist metadata via SpotDL scraper...")
    
    # Execute the SpotDL web scraper immediately
    return spotdl_client.playlist(url)
