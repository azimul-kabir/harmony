from pydantic import BaseModel


class SyncSourceRequest(BaseModel):
    spotify_url: str


class SyncSourceUpdateRequest(BaseModel):
    enabled: bool


class SyncSourceAutoSyncRequest(BaseModel):
    enabled: bool
    interval_minutes: int = 360
