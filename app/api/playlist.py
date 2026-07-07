from fastapi import APIRouter

router = APIRouter(
    prefix="/api/playlists",
    tags=["Playlists"],
)