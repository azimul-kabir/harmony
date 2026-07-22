"""Non-destructive genre tag writes for download-time provider metadata."""
from pathlib import Path
from mutagen import File

def write_genres(path: Path, values: list[str]) -> None:
    values = [value.strip() for value in values if value.strip()]
    if not values: return
    audio = File(path, easy=True)
    if audio is None: return
    audio["genre"] = values
    audio.save()
    reread = File(path, easy=True)
    if reread is None or list(reread.get("genre", [])) != values:
        raise RuntimeError("Genre tag verification failed")
