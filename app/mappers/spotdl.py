from app.domain.track import Track
from app.schemas.spotdl import SpotDLSong


def spotdl_song_to_track(song: SpotDLSong) -> Track:
    return Track(
        title=song.name,
        artist=song.artist,
        album=song.album_name,
        album_artist=song.album_artist,
        track=song.track_number,
        disc=song.disc_number,
        year=song.year,
        duration=float(song.duration),
        isrc=song.isrc or None,
        spotify_track_id=song.song_id,
        spotify_url=song.url,
    )
