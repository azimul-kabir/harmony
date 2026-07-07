from fastapi import APIRouter

from app.api.schemas.playlist import PlaylistImportRequest
from app.api.schemas.playlist_response import PlaylistResponse
from app.services.playlist import import_playlist

router = APIRouter(
    prefix="/api/playlists",
    tags=["Playlists"],
)


@router.post("/import", response_model=PlaylistResponse)
def import_spotify_playlist(request: PlaylistImportRequest):
    playlist = import_playlist(request.url)

    return PlaylistResponse.model_validate(playlist)