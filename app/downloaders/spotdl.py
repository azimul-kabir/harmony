import json
import subprocess

from app.core.config import get_settings


class SpotDLClient:
    def __init__(self):
        self.settings = get_settings()

    def playlist(self, url: str):
        result = subprocess.run(
            [
                self.settings.spotdl_path,
                "save",
                url,
                "--save-file",
                "-",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(result.stderr)

        start = result.stdout.find("[")

        if start == -1:
            raise RuntimeError("SpotDL did not return JSON.")

        songs = json.loads(result.stdout[start:])

        return songs