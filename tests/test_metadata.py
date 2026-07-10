from pathlib import Path

from app.services.metadata import read_metadata


def test_read_metadata():
    file = Path("test_music/06 - End of Beginning.mp3")

    if not file.exists():
        return

    metadata = read_metadata(file)

    assert metadata["title"] == "End of Beginning"
    assert metadata["artist"] == "Djo"
    assert metadata["album"] == "DECIDE"
