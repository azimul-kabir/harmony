from pydantic import BaseModel, Field


class DownloadRequest(BaseModel):
    # Reject an empty form submission before it reaches URL parsing or a provider.
    # This deliberately does not attempt to validate Spotify's complete URL grammar:
    # ``spotify_resource`` is the single authoritative parser for that.
    url: str = Field(min_length=1, max_length=2_048)


class DownloadBulkRequest(BaseModel):
    action: str
    download_ids: list[int] = Field(default_factory=list, max_length=100)
