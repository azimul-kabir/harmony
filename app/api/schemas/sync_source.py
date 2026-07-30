from pydantic import BaseModel


class SyncSourceRequest(BaseModel):
    source_url: str | None = None
    spotify_url: str | None = None


class SyncSourceUpdateRequest(BaseModel):
    enabled: bool


class SyncSourceAutoSyncRequest(BaseModel):
    enabled: bool
    interval_minutes: int = 360
