from sqlalchemy.orm import Session

from app.database.crud import find_song_by_title_artist
from app.domain.comparison import (
    ComparedTrack,
    PlaylistComparison,
    TrackStatus,
)
from app.domain.playlist import Playlist


def compare_with_library(
    db: Session,
    playlist: Playlist,
) -> PlaylistComparison:
    owned = 0
    missing = 0
    tracks: list[ComparedTrack] = []

    for track in playlist.tracks:
        song = find_song_by_title_artist(
            db,
            track.title,
            track.artist,
        )

        if song:
            status = TrackStatus.OWNED
            owned += 1
        else:
            status = TrackStatus.MISSING
            missing += 1

        tracks.append(
            ComparedTrack(
                track=track,
                status=status,
            )
        )

    return PlaylistComparison(
        playlist_name=playlist.name,
        total=playlist.track_count,
        owned=owned,
        missing=missing,
        tracks=tracks,
    )