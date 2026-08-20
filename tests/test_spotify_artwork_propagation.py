from mutagen.id3 import ID3

from app.database.crud_downloads import create_job
from app.database.session import SessionLocal
from app.mappers.spotdl import spotdl_song_to_track
from app.mappers.download_job import download_job_to_track
from app.providers import youtube_music
from app.schemas.spotdl import SpotDLSong


COVER_URL = "https://i.scdn.co/image/spotify-album-cover"


def _spotdl_song() -> SpotDLSong:
    return SpotDLSong.model_validate({
        "name": "Playlist Song", "artist": "Artist", "artists": ["Artist"],
        "album_name": "Album", "album_artist": "Artist", "duration": 180,
        "song_id": "spotify-track-id",
        "url": "https://open.spotify.com/track/spotify-track-id",
        "cover_url": COVER_URL,
    })


def test_spotdl_playlist_cover_survives_mapper_queue_and_worker():
    track = spotdl_song_to_track(_spotdl_song())
    assert track.cover_url == COVER_URL

    db = SessionLocal()
    try:
        job = create_job(db, track)
        assert job.cover_url == COVER_URL
        db.expire_all()
        assert download_job_to_track(job).cover_url == COVER_URL
    finally:
        db.close()


def test_propagated_spotify_artwork_creates_one_front_cover(tmp_path, monkeypatch):
    monkeypatch.setattr(
        youtube_music, "_fetch_artwork", lambda url: b"spotify-cover"
    )
    track = spotdl_song_to_track(_spotdl_song())
    artwork = youtube_music._download_artwork(track, "selected-video", 436)
    output = tmp_path / "track.mp3"
    output.write_bytes(b"audio placeholder")
    youtube_music._write_download_tags(output, track, {}, artwork)

    covers = [frame for frame in ID3(output).getall("APIC") if frame.type == 3]
    assert len(covers) == 1
    assert covers[0].data == b"spotify-cover"
