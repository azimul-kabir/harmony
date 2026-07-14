import json
import subprocess
from pathlib import Path

from app.core.config import get_settings
from app.domain.playlist import Playlist
from app.domain.track import Track
from app.mappers.spotdl import spotdl_song_to_track
from app.schemas.spotdl import SpotDLSong


class SpotDLClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def playlist(
        self,
        url: str,
    ) -> Playlist:
        result = self._run(
            [
                "save",
                url,
                "--audio",
                *self._audio_providers(),
                "--save-file",
                "-",
            ]
        )

        if result.returncode != 0:
            raise RuntimeError(result.stderr)

        songs = self._extract_json(result.stdout)

        validated = [
            SpotDLSong.model_validate(song)
            for song in songs
        ]

        if not validated:
            raise RuntimeError("Playlist is empty.")

        tracks = [
            spotdl_song_to_track(song)
            for song in validated
        ]

        first = validated[0]

        return Playlist(
            name=first.list_name or "Unknown Playlist",
            url=first.list_url or url,
            tracks=tracks,
        )

    def download(
        self,
        track: Track,
        output_dir: Path,
    ) -> Path:
        query = (
            track.spotify_url
            if track.spotify_url
            else f"{track.artist} - {track.title}"
        )

        result = self._run(
            [
                query,
                "--audio",
                *self._audio_providers(),
                "--output",
                str(output_dir),
            ]
        )

        if result.returncode != 0:
            raise RuntimeError(result.stderr)

        files = sorted(
            output_dir.glob("*"),
            key=lambda file: file.stat().st_mtime,
            reverse=True,
        )

        if not files:
            raise RuntimeError(
                "SpotDL did not produce any output file."
            )

        return files[0]

    def download_url(
        self,
        url: str,
        output_dir: Path,
    ) -> subprocess.CompletedProcess[str]:
        return self._run(
            [
                url,
                "--audio",
                *self._audio_providers(),
                "--output",
                str(output_dir),
            ]
        )

    def _audio_providers(self) -> list[str]:
        return [
            provider.strip()
            for provider in self.settings.audio_providers.split(",")
            if provider.strip()
        ]

    def _run(
        self,
        args: list[str],
    ) -> subprocess.CompletedProcess[str]:
        command = [
            self.settings.spotdl_path,
            *args,
        ]

        return subprocess.run(
            command,
            capture_output=True,
            text=True,
        )

    @staticmethod
    def _extract_json(
        stdout: str,
    ) -> list[dict]:
        start = stdout.find("[")

        if start == -1:
            raise RuntimeError(
                "SpotDL did not return JSON."
            )

        return json.loads(stdout[start:])