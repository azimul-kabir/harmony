from pydantic import BaseModel


class PlaylistImportRequest(BaseModel):
    url: str
