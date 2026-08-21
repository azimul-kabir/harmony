import json
import os
import subprocess
import tempfile
import shutil
import re
import signal
import time
import unicodedata
from difflib import SequenceMatcher
from dataclasses import dataclass
from pathlib import Path

from mutagen import File as MutagenFile, MutagenError

from app.core.config import get_settings
from app.core.logging import logger
from app.domain.playlist import Playlist
from app.domain.track import Track
from app.mappers.spotdl import spotdl_song_to_track
from app.schemas.spotdl import SpotDLSong
from app.services import settings_service
from app.database.session import SessionLocal
from app.domain.download_outcome import DownloadFailed


@dataclass(frozen=True, slots=True)
class AudioIdentity:
    title: str | None
    artist: str | None
    duration: float | None


class SpotDLFallbackTimeout(RuntimeError):
    """The bounded track-acquisition fallback exhausted its wall-clock budget."""


_VERSION_MARKERS = (
    "instrumental", "karaoke", "live", "remix", "sped up", "slowed",
    "acoustic", "demo", "radio edit", "remaster", "cover", "tribute",
)


def _normalized(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = re.sub(r"\b(feat(?:uring)?|ft|with)\.?\s+.*$", "", value)
    value = re.sub(r"\b(?:explicit|clean)(?: version)?\b", "", value)
    value = re.sub(r"[^\w\s]", " ", value)
    return " ".join(value.split())


def _markers(value: str | None) -> frozenset[str]:
    normalized = _normalized(value)
    return frozenset(marker for marker in _VERSION_MARKERS if marker in normalized)


def _title_without_non_version_qualifiers(value: str | None) -> str:
    """Remove parenthetical context that does not identify a recording version.

    Spotify sometimes includes soundtrack context in the canonical title (for
    example ``Earned It (Fifty Shades Of Grey)``), while the audio provider's
    embedded title contains only ``Earned It``.  Such context is safe to ignore
    only when it is bracketed and contains none of our material version markers.
    """
    value = value or ""

    def preserve_version(match: re.Match[str]) -> str:
        qualifier = match.group(1)
        return match.group(0) if _markers(qualifier) else " "

    without_qualifiers = re.sub(
        r"[\[(]([^\]\)]+)[\])]", preserve_version, value
    )
    return _normalized(without_qualifiers)


def _same_strict_title(requested: Track, candidate: str | None) -> bool:
    if _normalized(requested.title) == _normalized(candidate):
        return True
    requested_base = _title_without_non_version_qualifiers(requested.title)
    candidate_base = _title_without_non_version_qualifiers(candidate)
    if (
        requested_base
        and requested_base == candidate_base
        and _markers(requested.title) == _markers(candidate)
    ):
        return True

    # YouTube Music commonly appends the film/album name to an otherwise exact
    # song title (for example ``Song - Film Name``), while Spotify keeps that
    # context only in the album field. Accept that representation only when the
    # extra suffix identifies the requested album; arbitrary longer titles are
    # still rejected.
    album = _normalized(requested.album)
    if not album or _markers(requested.title) != _markers(candidate):
        return False
    for left, right in ((requested.title, candidate), (candidate, requested.title)):
        left_value = left or ""
        right_value = right or ""
        match = re.match(
            rf"^\s*{re.escape(left_value)}\s*(?:[-–—|:]|\bfrom\b)\s*(.+?)\s*$",
            right_value,
            flags=re.IGNORECASE,
        )
        if match and _title_similarity(album, match.group(1)) >= 0.72:
            return True
    return False


def _artist_credits(value: str | None) -> frozenset[str]:
    """Return normalized performers from common multi-artist tag formats."""
    credits = re.split(
        r"\s*(?:,|;|&|\+|/|\b(?:and|feat(?:uring)?|ft)\.?\b)\s*",
        value or "",
        flags=re.IGNORECASE,
    )
    return frozenset(filter(None, (_normalized(credit) for credit in credits)))


def _same_artist_credit(requested: str | None, candidate: str | None) -> bool:
    requested_normalized = _normalized(requested)
    candidate_normalized = _normalized(candidate)
    if requested_normalized == candidate_normalized:
        return True
    # Provider credits are not ordered consistently. A Spotify track may name
    # one primary performer while YouTube Music lists the same singer later in
    # a multi-artist tag, so require overlap rather than identical first artist.
    return bool(
        requested_normalized
        and candidate_normalized
        and _artist_credits(requested) & _artist_credits(candidate)
    )


def _title_similarity(requested: str | None, candidate: str | None) -> float:
    left = _normalized(requested)
    right = _normalized(candidate)
    if not left or not right:
        return 0.0
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if left_tokens.issubset(right_tokens) and _markers(candidate):
        return 0.9
    token_score = len(left_tokens & right_tokens) / max(
        len(left_tokens), len(right_tokens)
    )
    return max(token_score, SequenceMatcher(None, left, right).ratio())


def validate_track_identity(
    requested: Track,
    candidate: AudioIdentity,
    *,
    strict: bool = True,
) -> None:
    """Reject unrelated output while allowing a controlled fallback version."""
    if not candidate.title or not candidate.artist:
        raise DownloadFailed(
            "exact_match_unavailable", "Exact match unavailable", "validation",
            retryable=False, technical_detail="audio_identity_missing",
        )
    if not _same_artist_credit(requested.artist, candidate.artist):
        raise DownloadFailed(
            "exact_match_unavailable", "Exact match unavailable", "validation",
            retryable=False, technical_detail="artist_mismatch",
        )
    if strict and not _same_strict_title(requested, candidate.title):
        raise DownloadFailed(
            "exact_match_unavailable", "Exact match unavailable", "validation",
            retryable=False, technical_detail="title_mismatch",
        )
    if strict and _markers(requested.title) != _markers(candidate.title):
        raise DownloadFailed(
            "exact_match_unavailable", "Exact match unavailable", "validation",
            retryable=False, technical_detail="version_mismatch",
        )
    if not strict and _title_similarity(requested.title, candidate.title) < 0.72:
        raise DownloadFailed(
            "fallback_match_unavailable", "No safe fallback match was found", "validation",
            retryable=False, technical_detail="fallback_title_mismatch",
        )
    if requested.duration and candidate.duration:
        requested_duration = requested.duration
        # Album and individual-track jobs created before the duration-unit fix
        # stored Spotify's duration_ms value directly.  Keep retries of those
        # existing queued jobs valid while all newly resolved tracks use seconds.
        if requested_duration > candidate.duration * 100:
            requested_duration /= 1000
        tolerance = (
            max(12.0, min(25.0, requested_duration * 0.10))
            if not strict
            else max(5.0, min(10.0, requested_duration * 0.04))
        )
        if abs(requested_duration - candidate.duration) > tolerance:
            raise DownloadFailed(
                "exact_match_unavailable" if strict else "fallback_match_unavailable",
                "Exact match unavailable" if strict else "No safe fallback match was found",
                "validation", retryable=False,
                technical_detail="duration_mismatch",
            )


def fallback_candidate_score(requested: Track, candidate: AudioIdentity) -> float:
    """Rank only candidates that already passed controlled fallback validation."""
    title_score = _title_similarity(requested.title, candidate.title)
    marker_score = 1.0 if _markers(requested.title) == _markers(candidate.title) else 0.7
    duration_score = 0.5
    if requested.duration and candidate.duration:
        requested_duration = requested.duration / 1000 if requested.duration > candidate.duration * 100 else requested.duration
        duration_score = max(0.0, 1.0 - abs(requested_duration - candidate.duration) / max(requested_duration, 1.0))
    return round(title_score * 0.65 + duration_score * 0.25 + marker_score * 0.10, 4)

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
        timeout_seconds: int | None = None,
    ) -> Path:
        # Fetch current quality setting from database
        db = SessionLocal()
        try:
            downloads_settings = settings_service.get_settings_by_category(db, "downloads")
            quality = downloads_settings.get("audio_quality", "320k")
        finally:
            db.close()

        timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else self.settings.spotdl_fallback_timeout_seconds
        )
        if timeout_seconds <= 0:
            raise ValueError("SpotDL fallback timeout must be greater than zero.")

        # Direct acquisition has already performed the metadata-search ladder.
        # Give SpotDL one high-value rescue using the canonical Spotify identity
        # when possible, rather than serially replaying URL, ISRC, album, and
        # title searches with a separate timeout for each one.
        attempt: tuple[str, str, bool] | None = None
        if track.spotify_url:
            attempt = ("spotify_url_rescue", track.spotify_url, True)
        elif track.artist and track.title:
            attempt = (
                "metadata_rescue",
                f"{track.artist} - {track.title} {track.album or ''} audio".strip(),
                True,
            )
        if attempt is None:
            raise DownloadFailed(
                "exact_match_unavailable", "Exact match unavailable", "download",
                retryable=False, technical_detail="download_identity_missing",
            )
        
        with tempfile.TemporaryDirectory(dir=output_dir) as temp_dir:
            temp_path = Path(temp_dir)
            failures: list[DownloadFailed] = []
            for query_type, query, loose_match in (attempt,):
                attempt_started = time.monotonic()
                attempt_path = temp_path / query_type
                attempt_path.mkdir()
                output_template = str(attempt_path / "{artist} - {title}.{output-ext}")
                return_code: int | None = None
                output_count = 0
                reason_category = "provider_error"
                diagnostic = "SpotDL failed before returning a result"
                try:
                    command_args = [
                        query,
                        "--audio", *self._audio_providers(),
                        "--bitrate", quality,
                        "--output", output_template,
                        "--threads", "1",
                    ]
                    if self.settings.yt_dlp_cookie_file:
                        command_args.extend(
                            ["--cookie-file", self.settings.yt_dlp_cookie_file]
                        )
                    if loose_match:
                        command_args.append("--dont-filter-results")
                    result = self._run(command_args, timeout=timeout_seconds)
                    return_code = result.returncode
                    files = self._audio_files(attempt_path)
                    output_count = len(files)
                    diagnostic = self._diagnostic(
                        result.stdout, result.stderr, attempt_path
                    )

                    if return_code != 0:
                        reason_category = self._provider_reason(diagnostic)
                        raise DownloadFailed(
                            reason_category,
                            "The download provider could not obtain the requested track.",
                            "download",
                            retryable=reason_category != "provider_no_match",
                            technical_detail=(
                                diagnostic or f"SpotDL exited with code {return_code}"
                            ),
                        )
                    if output_count == 0:
                        reason_category = "exact_match_unavailable"
                        diagnostic = diagnostic or (
                            "SpotDL completed without producing an audio file"
                        )
                        raise DownloadFailed(
                            reason_category,
                            "Harmony could not obtain the requested track.",
                            "download", retryable=False, technical_detail=diagnostic,
                        )
                    if output_count != 1:
                        reason_category = "unexpected_output_count"
                        diagnostic = (
                            f"SpotDL produced {output_count} supported audio files"
                        )
                        raise DownloadFailed(
                            reason_category,
                            "The provider returned an unexpected number of files.",
                            "validation", retryable=False,
                            technical_detail=diagnostic,
                        )

                    downloaded_file = files[0]
                    identity = self._read_audio_identity(downloaded_file)
                    validate_track_identity(
                        track,
                        identity,
                        strict=not loose_match,
                    )
                    reason_category = "success"
                    final_path = output_dir / downloaded_file.name
                    final_path.unlink(missing_ok=True)
                    shutil.move(str(downloaded_file), str(final_path))
                    return final_path
                except SpotDLFallbackTimeout as exc:
                    reason_category = "spotdl_fallback_timeout"
                    diagnostic = self._bounded_diagnostic(str(exc), attempt_path)
                    failures.append(DownloadFailed(
                        reason_category,
                        "The SpotDL fallback exceeded its time limit.",
                        "download",
                        retryable=False,
                        technical_detail=diagnostic,
                    ))
                except DownloadFailed as exc:
                    reason_category = exc.reason_code
                    diagnostic = self._bounded_diagnostic(
                        exc.technical_detail or exc.message, attempt_path
                    )
                    failures.append(DownloadFailed(
                        exc.reason_code, exc.message, exc.stage, exc.provider,
                        exc.retryable, diagnostic,
                    ))
                except (LookupError, RuntimeError) as exc:
                    diagnostic = self._bounded_diagnostic(str(exc), attempt_path)
                    reason_category = "provider_no_match" if isinstance(exc, LookupError) else "provider_error"
                    failures.append(DownloadFailed(
                        reason_category, "The download provider could not obtain the requested track.",
                        "download", retryable=not isinstance(exc, LookupError),
                        technical_detail=diagnostic,
                    ))
                finally:
                    self._log_attempt(job_id, query_type, return_code, output_count,
                                      reason_category, diagnostic,
                                      time.monotonic() - attempt_started)

            raise failures[-1] from None

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

    @staticmethod
    def _read_audio_identity(path: Path) -> AudioIdentity:
        try:
            audio = MutagenFile(path, easy=True)
        except (MutagenError, OSError):
            return AudioIdentity(None, None, None)
        if audio is None:
            return AudioIdentity(None, None, None)

        def first(name: str) -> str | None:
            values = audio.tags.get(name, []) if audio.tags is not None else []
            return str(values[0]) if values else None

        duration = getattr(getattr(audio, "info", None), "length", None)
        return AudioIdentity(first("title"), first("artist"), duration)

    @staticmethod
    def _provider_reason(diagnostic: str | None) -> str:
        text = (diagnostic or "").casefold()
        if "429" in text or "rate limit" in text:
            return "provider_rate_limited"
        if "no match" in text or "no results" in text or "not found" in text:
            return "provider_no_match"
        if "unavailable" in text or "403" in text:
            return "provider_unavailable"
        return "provider_error"

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
        elapsed_seconds: float,
    ) -> None:
        logger.bind(
            job_id=job_id,
            query_type=query_type,
            return_code=return_code,
            output_file_count=output_count,
            reason_category=reason_category,
            diagnostic=diagnostic,
            elapsed_seconds=round(elapsed_seconds, 3),
        ).info(
            "SpotDL download attempt completed job={} query_type={} return_code={} "
            "output_files={} reason={} diagnostic={} elapsed_seconds={}",
            job_id, query_type, return_code, output_count, reason_category,
            diagnostic, round(elapsed_seconds, 3),
        )

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
        timeout: int = 120,
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
        # SpotDL 4.5 derives its runtime directories from Path.home() and uses
        # check-then-mkdir for its temp folder. Sharing one HOME between worker
        # processes therefore races with concurrent downloads. Give every
        # invocation an isolated home while keeping all temporary state under
        # Harmony's configured writable root.
        with tempfile.TemporaryDirectory(prefix="run-", dir=config_path) as runtime_dir:
            runtime_home = Path(runtime_dir)
            invocation_config = runtime_home / ".config" / "spotdl"
            invocation_config.mkdir(parents=True)
            environment = os.environ.copy()
            environment["HOME"] = str(runtime_home)
            environment["XDG_CONFIG_HOME"] = str(runtime_home / ".config")
            environment["HARMONY_SPOTDL_CONFIG_DIR"] = str(invocation_config)

            process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=environment,
                    start_new_session=True,
                )
            try:
                stdout, stderr = process.communicate(timeout=timeout)
                return subprocess.CompletedProcess(
                    command, process.returncode, stdout, stderr
                )
            except subprocess.TimeoutExpired as e:
                self._terminate_process_group(process)
                raise SpotDLFallbackTimeout(
                    f"SpotDL execution timed out after {timeout} seconds."
                ) from e

    @staticmethod
    def _terminate_process_group(process: subprocess.Popen[str]) -> None:
        """Terminate SpotDL and every downloader/transcoder child it spawned."""
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            process.terminate()
        try:
            process.communicate(timeout=2)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
        process.communicate()

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
