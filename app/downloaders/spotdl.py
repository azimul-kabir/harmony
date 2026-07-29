import json
import os
import subprocess
import tempfile
import shutil
import re
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import logger
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
        self.validate_executable()
        timeout = self.settings.spotify_playlist_metadata_timeout_seconds
        result = self._run(
            [
                "save",
                url,
                "--audio",
                *self._audio_providers(),
                "--save-file",
                "-",
            ],
            timeout=timeout,
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

    def validate_executable(self) -> str:
        """Return the usable SpotDL command or fail with an actionable message."""
        configured = self.settings.spotdl_path
        candidate = Path(configured)
        if candidate.is_absolute():
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return configured
        else:
            resolved = shutil.which(configured)
            if resolved:
                return resolved
        raise RuntimeError(
            "SpotDL is unavailable. Check SPOTDL_PATH in Harmony's runtime "
            "environment; Docker deployments should normally use 'spotdl'."
        )

    def download(
        self,
        track: Track,
        output_dir: Path,
        job_id: int | None = None,
    ) -> Path:
        # Fetch current quality setting from database
        db = SessionLocal()
        try:
            downloads_settings = settings_service.get_settings_by_category(db, "downloads")
            quality = downloads_settings.get("audio_quality", "320k")
        finally:
            db.close()

        # Each query is attempted exactly once.  In particular, a successful
        # SpotDL process is not necessarily a successful download: providers
        # can report a skip and exit zero without creating an audio file.
        queries_to_try: list[tuple[str, str]] = []
        if track.spotify_url:
            queries_to_try.append(("spotify_url", track.spotify_url))
            
        queries_to_try.append(("loose_search", f"{track.artist} - {track.title} audio"))
        
        with tempfile.TemporaryDirectory(dir=output_dir) as temp_dir:
            temp_path = Path(temp_dir)
            failures: list[dict[str, object]] = []

            for attempt_number, (query_type, query) in enumerate(queries_to_try, 1):
                attempt_path = temp_path / f"attempt-{attempt_number}"
                attempt_path.mkdir()
                output_template = str(attempt_path / "{artist} - {title}.{output-ext}")
                return_code: int | None = None
                output_count = 0
                reason_category = "execution_failure"
                diagnostic = "SpotDL failed before returning a result"
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
                    if query_type == "loose_search":
                        command_args.append("--dont-filter-results")
                        
                    result = self._run(command_args, timeout=300)
                    return_code = result.returncode
                    files = self._audio_files(attempt_path)
                    output_count = len(files)
                    diagnostic = self._diagnostic(result.stdout, result.stderr, attempt_path)

                    if result.returncode != 0:
                        reason_category = "nonzero_exit"
                    elif not files:
                        reason_category = "zero_exit_no_output"
                        if diagnostic is None:
                            diagnostic = "SpotDL completed without producing an output file"
                    else:
                        reason_category = "success"
                        downloaded_file = files[0]
                        final_path = output_dir / downloaded_file.name

                        if final_path.exists():
                            final_path.unlink()

                        shutil.move(str(downloaded_file), str(final_path))
                        self._log_attempt(
                            job_id,
                            query_type,
                            return_code,
                            output_count,
                            reason_category,
                            diagnostic,
                        )
                        return final_path

                    diagnostic = diagnostic or "SpotDL did not provide a diagnostic"
                except (LookupError, RuntimeError) as exc:
                    diagnostic = self._bounded_diagnostic(str(exc), attempt_path)
                    if isinstance(exc, LookupError) or "lookuperror" in str(exc).lower():
                        reason_category = "matching_failure"

                self._log_attempt(
                    job_id,
                    query_type,
                    return_code,
                    output_count,
                    reason_category,
                    diagnostic,
                )
                failures.append(
                    {
                        "query_type": query_type,
                        "return_code": return_code,
                        "category": reason_category,
                        "diagnostic": diagnostic,
                    }
                )

            final = failures[-1]
            query_types = ", ".join(str(item["query_type"]) for item in failures)
            if final["return_code"] is None:
                result_summary = "SpotDL did not return an exit code"
            elif final["return_code"] == 0:
                result_summary = "SpotDL returned zero with no output"
            else:
                result_summary = f"SpotDL returned nonzero ({final['return_code']})"
            raise RuntimeError(
                f"Could not download {track.artist or 'Unknown artist'} - "
                f"{track.title or 'Unknown title'} after {len(failures)} attempts "
                f"({query_types}). {result_summary}. Diagnostic: {final['diagnostic']}"
            )

    _AUDIO_EXTENSIONS = frozenset(
        {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".wma"}
    )
    _DIAGNOSTIC_PATTERN = re.compile(
        r"skipping|skipped|error|failed|no results|no match|audioprovidererror|"
        r"yt-dlp|\b403\b|\b429\b",
        re.IGNORECASE,
    )

    @classmethod
    def _audio_files(cls, directory: Path) -> list[Path]:
        """Return actual audio outputs recursively in deterministic order."""
        return sorted(
            (
                path
                for path in directory.rglob("*")
                if path.is_file() and path.suffix.lower() in cls._AUDIO_EXTENSIONS
            ),
            key=lambda path: path.relative_to(directory).as_posix(),
        )

    @classmethod
    def _diagnostic(cls, stdout: str, stderr: str, temp_path: Path) -> str | None:
        meaningful = [
            line.strip()
            for line in f"{stderr}\n{stdout}".splitlines()
            if cls._DIAGNOSTIC_PATTERN.search(line)
        ]
        if not meaningful:
            return None
        return cls._bounded_diagnostic(" | ".join(meaningful[-3:]), temp_path)

    @staticmethod
    def _bounded_diagnostic(message: str, temp_path: Path, limit: int = 500) -> str:
        safe_lines = [
            line
            for line in message.replace(str(temp_path), "[temporary output]").splitlines()
            if not line.lstrip().startswith(("Traceback (most recent call last):", "File \""))
        ]
        cleaned = " ".join(" ".join(safe_lines).split())
        # Provider diagnostics sometimes include local cache or output paths.
        # Keep URLs intact while removing Unix and Windows absolute paths.
        cleaned = re.sub(
            r"(?<![\w:/])(?:[A-Za-z]:\\|/)[^\s|]+", "[local path]", cleaned
        )
        return (cleaned[: limit - 1] + "…") if len(cleaned) > limit else cleaned

    @staticmethod
    def _log_attempt(
        job_id: int | None,
        query_type: str,
        return_code: int | None,
        output_count: int,
        reason_category: str,
        diagnostic: str | None,
    ) -> None:
        logger.bind(
            job_id=job_id,
            query_type=query_type,
            return_code=return_code,
            output_file_count=output_count,
            reason_category=reason_category,
            diagnostic=diagnostic,
        ).info("SpotDL download attempt completed")

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
        # SpotDL initializes its cache during module import.  Containers may
        # run with HOME unset or set to '/', where '/.config' is not writable.
        # Give every invocation an explicit writable XDG location instead of
        # allowing an otherwise valid download to fail before SpotDL starts.
        config_path = Path(
            os.environ.get(
                "HARMONY_SPOTDL_CONFIG_DIR",
                str(Path(tempfile.gettempdir()) / "harmony-spotdl"),
            )
        )
        config_path.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment["HOME"] = "/tmp"
        environment["XDG_CONFIG_HOME"] = str(config_path)
        environment["HARMONY_SPOTDL_CONFIG_DIR"] = str(config_path)
        
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=environment,
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
