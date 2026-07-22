from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

ENV_FILE = (
    ROOT / ".env.local"
    if (ROOT / ".env.local").exists()
    else ROOT / ".env.development"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Harmony"
    app_version: str = "1.6.0"

    host: str = "0.0.0.0"
    port: int = 8080

    database_url: str = "sqlite:////database/harmony.db"

    music_path: str = "/music"
    artwork_cache_path: str = "/database/artwork"

    download_path: str = "/downloads"
    staging_path: str = "/downloads/staging"
    failed_path: str = "/downloads/failed"

    log_level: str = "INFO"

    spotdl_path: str = "spotdl"
    use_official_spotify_api: bool = False
    spotify_metadata_provider: str = "spotify"
    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None
    spotify_genre_fetch_enabled: bool = True
    spotify_genre_max_values: int = 3
    spotify_genre_max_concurrent_requests: int = 4
    spotify_genre_include_featured_fallback: bool = True
    spotify_genre_merge_featured: bool = False
    spotify_genre_replace_existing: bool = False

    audio_providers: str = "youtube-music,youtube"

    max_parallel_downloads: int = 4

    library_watcher_enabled: bool = True
    library_watcher_debounce_seconds: float = 0.75

    musicbrainz_base_url: str = "https://musicbrainz.org/ws/2"
    musicbrainz_user_agent: str = "Harmony/1.6.0 (https://github.com/azimul-kabir/harmony)"
    musicbrainz_timeout_seconds: float = 10.0
    musicbrainz_max_retries: int = 3
    musicbrainz_backoff_seconds: float = 0.5
    musicbrainz_requests_per_second: float = 1.0
    musicbrainz_cache_ttl_seconds: int = 86400
    musicbrainz_max_concurrent_requests: int = 2
    cover_art_archive_base_url: str = "https://coverartarchive.org"
    cover_art_archive_timeout_seconds: float = 20.0
    cover_art_archive_max_bytes: int = 15 * 1024 * 1024
    metadata_discovery_chunk_size: int = 25
    metadata_discovery_max_batch_songs: int = 500


@lru_cache
def get_settings():
    return Settings()
