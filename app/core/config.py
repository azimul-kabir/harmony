from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Harmony"
    app_version: str = "0.3.0"

    host: str = "0.0.0.0"
    port: int = 8080

    database_url: str = "sqlite:////database/harmony.db"

    music_path: str = "/music"

    download_path: str = "/downloads"
    staging_path: str = "/downloads/staging"
    failed_path: str = "/downloads/failed"

    log_level: str = "INFO"

    # SpotDL
    spotdl_path: str = "spotdl"
    use_official_spotify_api: bool = False
    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None

    # Download
    max_parallel_downloads: int = 3

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()