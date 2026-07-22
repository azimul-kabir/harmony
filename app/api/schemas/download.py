from pydantic import BaseModel, Field


class DownloadRequest(BaseModel):
    url: str


class DownloadBulkRequest(BaseModel):
    action: str
    download_ids: list[int] = Field(default_factory=list, max_length=100)
