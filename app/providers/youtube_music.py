"""Public YouTube Music source using yt-dlp only (no login or cookies)."""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.core.config import get_settings
from app.core.logging import logger
from app.database.session import SessionLocal
from app.domain.track import Track
from app.providers.download_source import SourceResult
from app.services.download_processes import download_processes
from app.services import settings_service

_SUFFIX = re.compile(r"\s*[\[(](?:official (?:audio|video)|lyrics?|lyric video|visualizer)[^\])]*[\])]\s*$", re.I)
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,32}$")
_URL_IN_TEXT = re.compile(r"https?://\S+", re.I)


def clean_title(value: str | None) -> str:
    """Remove only high-confidence presentation suffixes from extractor titles."""
    return _SUFFIX.sub("", value or "").strip()


class YouTubeMusicSource:
    identifier = "youtube_music"
    display_name = "YouTube Music"

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def max_collection_items(self) -> int:
        return max(1, self.settings.youtube_music_max_playlist_items)

    def detect_url(self, url: str) -> tuple[str, str] | None:
        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix("www.")
        query = parse_qs(parsed.query)
        if host == "music.youtube.com":
            if parsed.path == "/watch" and query.get("v") and _VIDEO_ID.fullmatch(query["v"][0]):
                return "track", query["v"][0]
            if parsed.path == "/playlist" and query.get("list"):
                return "playlist", query["list"][0]
            if parsed.path.startswith("/browse/") and parsed.path != "/browse/":
                return "artist", parsed.path.rsplit("/", 1)[-1]
        # Standard URLs are a clear fallback only for explicit watch/playlist.
        if host in {"youtube.com", "m.youtube.com", "youtu.be"}:
            if parsed.path == "/playlist" and query.get("list") and query["list"][0].strip():
                return "playlist", query["list"][0]
            video_id = (query.get("v") or ([parsed.path.strip("/")] if host == "youtu.be" else []))
            if ((parsed.path == "/watch" and video_id) or (host == "youtu.be" and video_id)) and _VIDEO_ID.fullmatch(video_id[0]):
                return "track", video_id[0]
        return None

    def _run_json(self, target: str, *, flat: bool = False) -> dict:
        command = [self.settings.yt_dlp_path, "--dump-single-json", "--no-warnings", "--no-playlist"]
        if flat:
            command.remove("--no-playlist")
            # Request one additional entry so oversized playlists can be rejected
            # rather than silently truncated.
            command.extend(["--flat-playlist", "--playlist-end", str(self.max_collection_items + 1)])
        command.append(target)
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=self.settings.youtube_music_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("YouTube Music timed out. Please try again.") from exc
        if result.returncode:
            raise ValueError("YouTube Music could not resolve this item. It may be unavailable in your region.")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("YouTube Music returned an unsupported response.") from exc

    def _result(self, data: dict, item_type: str = "song") -> SourceResult:
        item_id = str(data.get("id") or data.get("url") or "")
        title = clean_title(data.get("track") or data.get("title")) or "Unknown title"
        artist = data.get("artist") or data.get("uploader")
        if artist and artist.endswith(" - Topic"):
            artist = artist[:-8]
        thumbs = data.get("thumbnails") or []
        artwork = thumbs[-1].get("url") if thumbs else data.get("thumbnail")
        canonical_url = f"https://music.youtube.com/watch?v={item_id}" if _VIDEO_ID.fullmatch(item_id) else data.get("webpage_url")
        return SourceResult(self.identifier, item_id, item_type, title, artist, data.get("album"), data.get("album_artist"), data.get("duration"), data.get("release_year") or data.get("year"), data.get("track_number"), data.get("disc_number"), data.get("age_limit") == 18, artwork, canonical_url, data.get("playlist_count"))

    def search(self, query: str, limit: int = 20) -> list[SourceResult]:
        bounded = max(1, min(limit, self.settings.youtube_music_max_search_results))
        data = self._run_json(f"ytsearch{bounded}:{query}", flat=True)
        entries = data.get("entries") or []
        return [self._result(entry) for entry in entries if entry and entry.get("id")]

    def resolve(self, url: str) -> list[Track]:
        detected = self.detect_url(url)
        if not detected:
            raise ValueError("Unsupported YouTube Music URL.")
        item_type, _ = detected
        data = self._run_json(url, flat=item_type != "track")
        entries = data.get("entries") if item_type != "track" else [data]
        if item_type != "track" and len(entries or []) > self.max_collection_items:
            raise ValueError(f"YouTube playlist exceeds the {self.max_collection_items}-track limit.")
        tracks: list[Track] = []
        seen: set[str] = set()
        for index, entry in enumerate(entries or [], start=1):
            result = self._result(entry)
            if not result.item_id or result.item_id in seen:
                continue
            seen.add(result.item_id)
            tracks.append(Track(title=result.title, artist=result.artist or "Unknown Artist", album=result.album or data.get("title"), album_artist=result.album_artist, track=result.track_number or index, disc=result.disc_number, year=result.year, duration=result.duration, cover_url=result.artwork_url, source_provider=self.identifier, source_item_id=result.item_id, source_url=result.source_url))
        if not tracks:
            raise ValueError("YouTube Music collection is empty or unavailable.")
        return tracks

    def _download_command(
        self,
        *,
        target: str,
        template: str,
        quality: str,
        square_artwork: bool,
    ) -> list[str]:
        command = [
            self.settings.yt_dlp_path,
            "--no-playlist",
            "-f",
            "bestaudio/best",
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            quality,
            "--embed-metadata",
        ]
        if square_artwork:
            command.extend([
                "--convert-thumbnails",
                "jpg",
                "--postprocessor-args",
                "ThumbnailsConvertor+ffmpeg_o:-vf crop=min(iw\\,ih):min(iw\\,ih)",
            ])
        command.extend(["--embed-thumbnail", "-o", template, target])
        return command

    @staticmethod
    def _thumbnail_conversion_failed(stderr: str) -> bool:
        message = stderr.lower()
        return (
            "convert-thumbnails" in message
            or ("thumbnail" in message and ("error" in message or "failed" in message))
        )

    @staticmethod
    def _failure_summary(stderr: str) -> str:
        """Log a bounded diagnostic without leaking the source URL or paths."""
        lines = [line.strip() for line in stderr.splitlines() if line.strip()]
        summary = lines[-1] if lines else "yt-dlp exited without an error message"
        summary = _URL_IN_TEXT.sub("<url>", summary)
        return summary[:300]

    @staticmethod
    def _clear_temporary_outputs(temporary: str) -> None:
        for path in Path(temporary).iterdir():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

    def _run_download_process(self, command: list[str], job_id: int | None) -> tuple[int, str, str]:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        if job_id is not None and not download_processes.register(job_id, process):
            try:
                import os
                import signal
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=3)
            except OSError:
                pass
            raise ValueError("YouTube Music download was cancelled.")
        try:
            stdout, stderr = process.communicate(timeout=self.settings.youtube_music_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            if job_id is not None:
                download_processes.cancel(job_id)
            else:
                process.terminate()
                process.wait(timeout=3)
            raise ValueError("YouTube Music download timed out.") from exc
        finally:
            if job_id is not None:
                download_processes.unregister(job_id, process)
        return process.returncode, stdout, stderr

    def download(self, track: Track, output_dir: str, job_id: int | None = None) -> Path:
        target = track.source_url or track.spotify_url
        if not target:
            raise ValueError("YouTube Music track is missing its source URL.")
        output = Path(output_dir)
        with tempfile.TemporaryDirectory(dir=output) as temporary:
            template = str(Path(temporary) / "%(title)s.%(ext)s")
            db = SessionLocal()
            try:
                quality = settings_service.get_settings_by_category(db, "downloads").get("audio_quality", self.settings.youtube_music_audio_quality)
            finally:
                db.close()
            command = self._download_command(target=target, template=template, quality=quality, square_artwork=True)
            returncode, _stdout, stderr = self._run_download_process(command, job_id)
            if returncode and self._thumbnail_conversion_failed(stderr):
                logger.warning("YouTube Music thumbnail conversion failed; retrying audio download without square artwork: {}", self._failure_summary(stderr))
                self._clear_temporary_outputs(temporary)
                command = self._download_command(target=target, template=template, quality=quality, square_artwork=False)
                returncode, _stdout, stderr = self._run_download_process(command, job_id)
            if returncode:
                logger.warning("YouTube Music downloader exited with code {}: {}", returncode, self._failure_summary(stderr))
                raise ValueError("YouTube Music could not download this track. It may be unavailable.")
            files = sorted(Path(temporary).glob("*.mp3"), key=lambda file: file.stat().st_mtime, reverse=True)
            if not files:
                raise ValueError("YouTube Music did not produce an audio file.")
            destination = output / files[0].name
            files[0].replace(destination)
            return destination
