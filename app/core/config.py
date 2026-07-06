from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Harmony"
    app_version: str = "0.1.0"

    host: str = "0.0.0.0"
    port: int = 8080

    database_url: str = "sqlite:////database/harmony.db"

    music_path: str = "/music"

    download_path: str = "/downloads"

    staging_path: str = "/downloads/staging"

    failed_path: str = "/downloads/failed"

    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()