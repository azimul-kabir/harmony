from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.database.models import Playlist, SyncSource
from app.services.playlist_manager import count_m3u_entries, playlist_file_path
from app.services.auto_playlists import definitions as auto_playlist_definitions
from app.web.templates import templates, template_context

router = APIRouter(tags=["web"])

@router.get("/playlists")
def playlists_page(request: Request, db: Session = Depends(get_db)):
    playlists = db.query(Playlist).order_by(Playlist.name).all()
    sources = {
        source.spotify_id: source
        for source in db.query(SyncSource).all()
    }
    playlist_cards = []
    for playlist in playlists:
        file_path = playlist_file_path(playlist.name)
        playlist_cards.append(
            {
                "playlist": playlist,
                "source": sources.get(playlist.spotify_id),
                "exported_count": count_m3u_entries(file_path),
                "m3u_exists": file_path.is_file(),
            }
        )

    return templates.TemplateResponse(
        "playlists.html",
        template_context(
            request=request, 
            page="playlists",
            playlists=playlist_cards,
            auto_playlists=auto_playlist_definitions(db),
        ),
    )
