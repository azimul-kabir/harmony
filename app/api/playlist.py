from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas.comparison import PlaylistComparisonResponse
from app.api.schemas.playlist import PlaylistImportRequest
from app.api.schemas.playlist_response import PlaylistResponse
from app.database.session import get_db
from app.services.comparison import compare_with_library
from app.services.playlist import import_playlist

from app.services.playlist_download import download_playlist

from pydantic import BaseModel

router = APIRouter(
    prefix="/api/playlists",
    tags=["Playlists"],
)


class PlaylistDownloadRequest(BaseModel):
    url: str


@router.post("/import", response_model=PlaylistResponse)
def import_spotify_playlist(request: PlaylistImportRequest):
    playlist = import_playlist(request.url)

    return PlaylistResponse.model_validate(playlist)


@router.post("/compare", response_model=PlaylistComparisonResponse)
def compare_spotify_playlist(
    request: PlaylistImportRequest,
    db: Session = Depends(get_db),
):
    playlist = import_playlist(request.url)

    comparison = compare_with_library(db, playlist)

    return PlaylistComparisonResponse.model_validate(comparison)


@router.post("/download")
def download(
    request: PlaylistDownloadRequest,
    db: Session = Depends(get_db),
):
    return download_playlist(
        db=db,
        url=request.url,
    )