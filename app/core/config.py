from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

ENV_FILE = ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Harmony"
    app_version: str = "3.0.0"

    host: str = "0.0.0.0"
    port: int = 8080

    web_auth_enabled: bool = True
    web_auth_username: str = "admin"
    web_auth_password: str = ""
    web_auth_session_hours: int = 12
    web_auth_secure_cookie: bool = False

    database_url: str = "sqlite:////database/harmony.db"

    music_path: str = "/music"
    artwork_cache_path: str = "/database/artwork"

    download_path: str = "/downloads"
    staging_path: str = "/downloads/staging"
    failed_path: str = "/downloads/failed"
    library_upload_max_file_bytes: int = 1024 * 1024 * 1024
    library_upload_max_files: int = 200

    log_level: str = "INFO"

    spotdl_path: str = "spotdl"
    spotdl_fallback_timeout_seconds: int = 45
    spotify_playlist_metadata_timeout_seconds: int = 3600
    yt_dlp_path: str = "yt-dlp"
    yt_dlp_cookie_file: str | None = None
    youtube_music_enabled: bool = True
    youtube_music_timeout_seconds: int = 300
    youtube_music_audio_quality: str = "0"
    youtube_music_max_playlist_items: int = 500
    youtube_music_max_search_results: int = 25
    youtube_music_max_queue_items: int = 500
    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None
    # Ordered providers passed to SpotDL for audio candidate discovery.
    audio_providers: str = "youtube-music,youtube"

    max_parallel_downloads: int = 2

    library_watcher_enabled: bool = True
    library_watcher_debounce_seconds: float = 0.75

    navidrome_url: str = ""
    navidrome_username: str = ""
    navidrome_password: str = ""
    navidrome_timeout_seconds: float = 5.0
    navidrome_max_retries: int = 2
    navidrome_playlist_reimport_enabled: bool = True
    navidrome_playlist_reimport_debounce_seconds: float = 10.0
    navidrome_playlist_reimport_poll_seconds: float = 2.0
    navidrome_playlist_reimport_scan_timeout_seconds: float = 900.0
    cover_art_archive_base_url: str = "https://coverartarchive.org"
    cover_art_archive_timeout_seconds: float = 20.0
    cover_art_archive_max_bytes: int = 15 * 1024 * 1024
    musicbrainz_base_url: str = "https://musicbrainz.org/ws/2"
    musicbrainz_timeout_seconds: float = 12.0



@lru_cache
def get_settings():
    return Settings()
