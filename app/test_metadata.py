from pathlib import Path

from app.services.metadata import read_metadata

music_dir = Path("/music")

for song in music_dir.rglob("*"):
    if song.suffix.lower() in {
        ".flac",
        ".mp3",
        ".m4a",
        ".aac",
        ".ogg",
        ".opus",
        ".wav",
    }:
        print(read_metadata(song))
        break