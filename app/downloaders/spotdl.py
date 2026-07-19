import json
import subprocess
import tempfile
import shutil
from pathlib import Path

from app.core.config import get_settings
from app.domain.playlist import Playlist
from app.domain.track import Track
from app.mappers.spotdl import spotdl_song_to_track
from app.schemas.spotdl import SpotDLSong
from app.services import settings_service
from app.database.session import SessionLocal

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
            ],
            timeout=1200  # 20 MINUTES: Generous timeout for massive playlist scraping
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
        # Fetch current quality setting from database
        db = SessionLocal()
        try:
            downloads_settings = settings_service.get_settings_by_category(db, "downloads")
            quality = downloads_settings.get("audio_quality", "320k")
        finally:
            db.close()

        # Define the queries as tuples: (query_string, use_loose_matching_flag)
        queries_to_try = []
        if track.spotify_url:
            queries_to_try.append((track.spotify_url, False))
            
        queries_to_try.append((f"{track.artist} - {track.title} audio", True))
        
        with tempfile.TemporaryDirectory(dir=output_dir) as temp_dir:
            temp_path = Path(temp_dir)
            output_template = f"{temp_path}/{{artist}} - {{title}}.{{output-ext}}"
            
            last_error = None
            
            # Loop through our query attempts
            for query, loose_match in queries_to_try:
                try:
                    command_args = [
                        query,
                        "--audio",
                        *self._audio_providers(),
                        "--bitrate", quality,
                        "--output", output_template,
                        "--threads", "1", 
                    ]
                    
                    # Inject the override flag for the fallback attempt
                    if loose_match:
                        command_args.append("--dont-filter-results")
                        
                    result = self._run(command_args, timeout=300)
                    
                    if result.returncode != 0:
                        raise RuntimeError(result.stderr)
                        
                    files = sorted(
                        temp_path.glob("*"),
                        key=lambda file: file.stat().st_mtime,
                        reverse=True,
                    )
                    
                    if not files:
                        error_msg = result.stdout.strip() or result.stderr.strip() or "No matching audio found."
                        error_msg = error_msg.split('\n')[-1] 
                        raise RuntimeError(f"SpotDL Skipped: {error_msg}")
                        
                    downloaded_file = files[0]
                    final_path = output_dir / downloaded_file.name
                    
                    if final_path.exists():
                        final_path.unlink()
                        
                    shutil.move(str(downloaded_file), str(final_path))
                    
                    return final_path
                    
                except RuntimeError as e:
                    last_error = e
                    # Silently catch the LookupError and proceed to the next fallback attempt
                    if "LookupError" in str(e):
                        continue
                    else:
                        raise e
                        
            # If all fallback attempts fail, raise the final error to the UI
            raise last_error

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
                "--threads",
                "1",
            ],
            timeout=300
        )

    def _audio_providers(self) -> list[str]:
        return ["youtube-music", "youtube"]

    def _run(
        self,
        args: list[str],
        timeout: int = 120, # Default fallback timeout
    ) -> subprocess.CompletedProcess[str]:
        command = [
            self.settings.spotdl_path,
            *args,
        ]
        
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"SpotDL execution timed out after {timeout} seconds.") from e

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
