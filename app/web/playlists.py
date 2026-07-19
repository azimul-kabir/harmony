from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.database.models import Playlist
from app.web.templates import templates, template_context

router = APIRouter(tags=["web"])

@router.get("/playlists")
def playlists_page(request: Request, db: Session = Depends(get_db)):
    playlists = db.query(Playlist).order_by(Playlist.name).all()
    
    return templates.TemplateResponse(
        "playlists.html",
        template_context(
            request=request, 
            page="playlists",
            playlists=playlists
        ),
    )
