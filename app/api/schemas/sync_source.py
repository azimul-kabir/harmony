from pydantic import BaseModel


class SyncSourceRequest(BaseModel):
    spotify_url: str