from pydantic import BaseModel


class DownloadRequest(BaseModel):
    spotify_url: str


class DownloadJobResponse(BaseModel):
    id: int

    spotify_url: str

    title: str
    artist: str

    status: str

    model_config = {
        "from_attributes": True,
    }