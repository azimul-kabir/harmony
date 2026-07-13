from pydantic import BaseModel


class SyncSourceRequest(BaseModel):
    spotify_url: str


class SyncSourceUpdateRequest(BaseModel):
    enabled: bool