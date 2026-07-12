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
    app_version: str = "0.5.0"

    host: str = "0.0.0.0"
    port: int = 8080

    database_url: str = "sqlite:////database/harmony.db"

    music_path: str = "/music"

    download_path: str = "/downloads"
    staging_path: str = "/downloads/staging"
    failed_path: str = "/downloads/failed"

    log_level: str = "INFO"

    spotdl_path: str = "spotdl"
    use_official_spotify_api: bool = False
    spotify_metadata_provider: str = "spotify"
    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None

    audio_providers: str = "youtube-music,youtube"

    max_parallel_downloads: int = 3


@lru_cache
def get_settings():
    return Settings()