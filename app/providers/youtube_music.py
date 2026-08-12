"""Public YouTube Music source using yt-dlp only (no login or cookies)."""
import json
import re
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from mutagen.id3 import APIC, COMM, ID3, ID3NoHeaderError, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK, TSRC, TXXX
from PIL import Image, ImageOps
from ytmusicapi import YTMusic
from app.core.config import get_settings
from app.core.logging import logger
from app.database.session import SessionLocal
from app.domain.playlist import Playlist
from app.domain.track import Track
from app.providers.download_source import SourceResult
from app.services import settings_service
from app.services.download_processes import download_processes


_SUFFIX = re.compile(r"\s*[\[(](?:official (?:audio|video)|lyrics?|lyric video|visualizer)[^\])]*[\])]\s*$", re.I)
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,32}$")
_ARTWORK_MAX_BYTES = 15 * 1024 * 1024
_ARTWORK_SIZE = 1200


def _yt_dlp_command(executable: str) -> list[str]:
    """Build a yt-dlp command with Harmony's bundled JS runtime enabled."""
    command = [executable]
    deno = shutil.which("deno")
    if deno:
        command.extend(["--js-runtimes", f"deno:{deno}"])
    else:
        logger.warning(
            "Deno was not found on PATH; YouTube extraction may be incomplete"
        )
    return command


def clean_title(value: str | None) -> str:
    """Remove only high-confidence presentation suffixes from extractor titles."""
    return _SUFFIX.sub("", value or "").strip()


def _artist_names(data: dict) -> list[str]:
    return [
        str(artist["name"]).strip()
        for artist in data.get("artists") or []
        if isinstance(artist, dict) and artist.get("name")
    ]


def normalize_url(url: str) -> str:
    """Give public URLs without a scheme the same treatment as the FAB UI."""
    value = url.strip()
    return value if "://" in value else f"https://{value}"


def watch_url(item_id: str) -> str:
    """Keep YouTube Music tracks on the Music watch endpoint."""
    return f"https://music.youtube.com/watch?v={item_id}"


def _best_artwork(data: dict) -> str | None:
    """Prefer a real square album image over YouTube's widescreen preview."""
    candidates = [
        item
        for item in (data.get("thumbnail") or data.get("thumbnails") or [])
        if isinstance(item, dict) and item.get("url")
    ]
    if not candidates:
        thumbnail = data.get("thumbnail")
        return thumbnail if isinstance(thumbnail, str) else None

    def score(item: dict) -> tuple[float, int]:
        width, height = item.get("width") or 0, item.get("height") or 0
        if not width or not height:
            return (-2.0, 0)
        # Aspect ratio is more important than raw resolution. YouTube video
        # previews are generally larger than the album cover thumbnails.
        return (-abs(width / height - 1), min(width, height))

    return max(candidates, key=score)["url"]


def _youtube_music_track(item_id: str) -> dict:
    """Fetch the audio track card, whose thumbnail is the actual album cover."""
    tracks = YTMusic().get_watch_playlist(videoId=item_id, limit=1).get("tracks") or []
    return next(
        (
            track
            for track in tracks
            if track.get("videoId") == item_id
            or (track.get("counterpart") or {}).get("videoId") == item_id
        ),
        tracks[0] if tracks else {},
    )


def _is_video_preview(url: str | None) -> bool:
    if not url:
        return False
    hostname = urlparse(url).hostname or ""
    return hostname == "img.youtube.com" or hostname.endswith(".ytimg.com")


def _youtube_music_artwork(item_id: str) -> str | None:
    """Resolve album artwork, rather than the watch page's video thumbnail."""
    client = YTMusic()
    tracks = client.get_watch_playlist(videoId=item_id, limit=1).get("tracks") or []
    track = next(
        (
            candidate
            for candidate in tracks
            if candidate.get("videoId") == item_id
            or (candidate.get("counterpart") or {}).get("videoId") == item_id
        ),
        tracks[0] if tracks else {},
    )

    album_id = (track.get("album") or {}).get("id")
    if album_id:
        album_url = _best_artwork(client.get_album(album_id))
        if album_url and not _is_video_preview(album_url):
            return album_url

    track_url = _best_artwork(track)
    return track_url if track_url and not _is_video_preview(track_url) else None


def _square_jpeg(content: bytes) -> bytes:
    """Center-crop artwork to a bounded, high-quality 1:1 JPEG."""
    with Image.open(BytesIO(content)) as source:
        source.load()
        size = min(_ARTWORK_SIZE, source.width, source.height)
        image = ImageOps.fit(source.convert("RGB"), (size, size), method=Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, "JPEG", quality=92, optimize=True)
        return output.getvalue()


def _fetch_artwork(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Artwork URL is not HTTPS.")
    if _is_video_preview(url):
        raise ValueError("YouTube video previews are not album artwork.")
    request = Request(url, headers={"User-Agent": "Harmony/2 YouTubeMusicArtwork"})
    with urlopen(request, timeout=20) as response:
        content = response.read(_ARTWORK_MAX_BYTES + 1)
    if len(content) > _ARTWORK_MAX_BYTES:
        raise ValueError("Artwork exceeds the size limit.")
    return _square_jpeg(content)


def _download_artwork_url(track: Track) -> str | None:
    """Resolve album art lazily for playlist-sync jobs with flat metadata."""
    if track.cover_url:
        return track.cover_url

    item_id = track.source_item_id
    if not item_id and track.source_url:
        parsed = urlparse(normalize_url(track.source_url))
        item_id = (parse_qs(parsed.query).get("v") or [None])[0]
    if not item_id or not _VIDEO_ID.fullmatch(item_id):
        return None
    return _best_artwork(_youtube_music_track(item_id))


def _write_download_tags(path: Path, track: Track, extracted: dict, artwork: bytes | None) -> None:
    """Replace sparse extractor tags with Harmony's canonical queue metadata."""
    artist = track.artist or extracted.get("artist") or extracted.get("uploader") or "Unknown Artist"
    if artist.endswith(" - Topic"):
        artist = artist[:-8]
    album_artist = track.album_artist or extracted.get("album_artist") or artist
    album = track.album or extracted.get("album") or "Singles"
    title = track.title or clean_title(extracted.get("track") or extracted.get("title")) or "Unknown Title"
    year = track.year or extracted.get("release_year") or extracted.get("release_date") or extracted.get("upload_date")

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    values = {
        "TIT2": TIT2(encoding=3, text=title),
        "TPE1": TPE1(encoding=3, text=artist),
        "TPE2": TPE2(encoding=3, text=album_artist),
        "TALB": TALB(encoding=3, text=album),
    }
    if track.track or extracted.get("track_number"):
        values["TRCK"] = TRCK(encoding=3, text=str(track.track or extracted["track_number"]))
    if track.disc or extracted.get("disc_number"):
        values["TPOS"] = TPOS(encoding=3, text=str(track.disc or extracted["disc_number"]))
    if year:
        values["TDRC"] = TDRC(encoding=3, text=str(year)[:4])
    if track.genre:
        values["TCON"] = TCON(encoding=3, text=track.genre)
    isrc = track.isrc or extracted.get("isrc")
    if isrc:
        values["TSRC"] = TSRC(encoding=3, text=str(isrc))
    for frame_id, frame in values.items():
        tags.setall(frame_id, [frame])
    tags.delall("COMM")
    tags.add(COMM(encoding=3, lang="eng", desc="Source", text=track.source_url or extracted.get("webpage_url") or "YouTube Music"))
    tags.delall("TXXX:YouTube Music ID")
    source_id = track.source_item_id or extracted.get("id")
    if source_id:
        tags.add(TXXX(encoding=3, desc="YouTube Music ID", text=str(source_id)))
    if artwork:
        tags.setall("APIC", [item for item in tags.getall("APIC") if item.type != 3])
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=artwork))
    tags.save(path, v2_version=3)


class YouTubeMusicSource:
    identifier = "youtube_music"
    display_name = "YouTube Music"

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def max_collection_items(self) -> int:
        return max(1, self.settings.youtube_music_max_playlist_items)

    def detect_url(self, url: str) -> tuple[str, str] | None:
        parsed = urlparse(normalize_url(url))
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
        command = _yt_dlp_command(self.settings.yt_dlp_path)
        command.extend(["--dump-single-json", "--no-warnings", "--no-playlist"])
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
        music_data: dict = {}
        if _VIDEO_ID.fullmatch(item_id):
            try:
                music_data = _youtube_music_track(item_id)
            except Exception as exc:
                logger.warning("Could not fetch canonical YouTube Music metadata for {}: {}", item_id, exc)
        title = clean_title(
            music_data.get("title") or data.get("track") or data.get("title")
        ) or "Unknown title"
        music_artists = _artist_names(music_data)
        artist = ", ".join(music_artists) or data.get("artist") or data.get("uploader")
        if artist and artist.endswith(" - Topic"):
            artist = artist[:-8]
        music_album = music_data.get("album") or {}
        album = music_album.get("name") if isinstance(music_album, dict) else None
        album = album or data.get("album")
        album_artist = (
            music_artists[0]
            if music_artists
            else data.get("album_artist") or artist
        )
        # yt-dlp extracts the YouTube *video* preview.  The audio-only Music
        # watch card exposes the square album cover shown in YouTube Music.
        artwork = _best_artwork(music_data)
        canonical_url = watch_url(item_id) if _VIDEO_ID.fullmatch(item_id) else data.get("webpage_url")
        return SourceResult(self.identifier, item_id, item_type, title, artist, album, album_artist, data.get("duration") or music_data.get("duration_seconds"), data.get("release_year") or data.get("year"), data.get("track_number"), data.get("disc_number"), music_data.get("isExplicit") or data.get("age_limit") == 18, artwork, canonical_url, data.get("playlist_count"))

    def search(self, query: str, limit: int = 20) -> list[SourceResult]:
        bounded = max(1, min(limit, self.settings.youtube_music_max_search_results))
        data = self._run_json(f"ytsearch{bounded}:{query}", flat=True)
        entries = data.get("entries") or []
        return [self._result(entry) for entry in entries if entry and entry.get("id")]

    def _resolve(self, url: str) -> tuple[str, list[Track]]:
        target = normalize_url(url)
        detected = self.detect_url(target)
        if not detected:
            raise ValueError("Unsupported YouTube Music URL.")
        item_type, item_id = detected
        # Keep an explicitly supplied standard YouTube URL on that endpoint.
        # Rewriting it to music.youtube.com can apply different Workspace or
        # network restrictions even though the video is public on YouTube.
        if item_type == "track" and urlparse(target).hostname == "music.youtube.com":
            target = watch_url(item_id)
        data = self._run_json(target, flat=item_type != "track")
        entries = data.get("entries") if item_type != "track" else [data]
        if item_type != "track" and len(entries or []) > self.max_collection_items:
            raise ValueError(f"YouTube playlist exceeds the {self.max_collection_items}-track limit.")
        tracks: list[Track] = []
        seen: set[str] = set()
        for entry in entries or []:
            # Flat playlist records omit most music tags and frequently expose
            # only a widescreen video thumbnail. Hydrate every item before it
            # enters the durable queue so retries retain complete metadata.
            if item_type != "track" and entry.get("id"):
                try:
                    entry = self._run_json(watch_url(str(entry["id"])))
                except ValueError:
                    logger.warning("Could not hydrate YouTube Music playlist item {}; using flat metadata", entry.get("id"))
            result = self._result(entry)
            if not result.item_id or result.item_id in seen:
                continue
            seen.add(result.item_id)
            source_url = target if item_type == "track" else result.source_url
            tracks.append(Track(title=result.title, artist=result.artist or "Unknown Artist", album=result.album or "Singles", album_artist=result.album_artist, track=result.track_number, disc=result.disc_number, year=result.year, duration=result.duration, cover_url=result.artwork_url, source_provider=self.identifier, source_item_id=result.item_id, source_url=source_url))
        if not tracks:
            raise ValueError("YouTube Music collection is empty or unavailable.")
        return clean_title(data.get("title")) or "YouTube Music Playlist", tracks

    def resolve(self, url: str) -> list[Track]:
        return self._resolve(url)[1]

    def resolve_playlist(self, url: str) -> Playlist:
        name, tracks = self._resolve(url)
        return Playlist(name=name, url=normalize_url(url), tracks=tracks)

    def download(self, track: Track, output_dir: str, job_id: int | None = None) -> Path:
        target = track.source_url or track.spotify_url
        if not target:
            raise ValueError("YouTube Music track is missing its source URL.")
        detected = self.detect_url(target)
        if (
            detected
            and detected[0] == "track"
            and urlparse(target).hostname == "music.youtube.com"
        ):
            target = watch_url(detected[1])
        else:
            target = normalize_url(target)
        output = Path(output_dir)
        with tempfile.TemporaryDirectory(dir=output) as temporary:
            template = str(Path(temporary) / "%(title)s.%(ext)s")
            db = SessionLocal()
            try:
                quality = settings_service.get_settings_by_category(
                    db,
                    "downloads",
                ).get(
                    "audio_quality",
                    self.settings.youtube_music_audio_quality,
                )
            finally:
                db.close()

            command = _yt_dlp_command(self.settings.yt_dlp_path) + [
                "--no-playlist",
                "-f",
                "bestaudio/best",
                "-x",
                "--audio-format",
                "mp3",
                "--audio-quality",
                quality,
                "--write-info-json",
                "-o",
                template,
                target,
            ]
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
            result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            if result.returncode:
                # Keep yt-dlp's actionable diagnostics in the server log while
                # returning a stable, non-sensitive message to the browser.
                detail = (result.stderr or result.stdout).strip()
                logger.warning("YouTube Music download failed for job #{}: {}", job_id, detail[-2000:] or "yt-dlp exited without output")
                raise ValueError("YouTube Music could not download this track. It may be unavailable.")
            files = sorted(Path(temporary).glob("*.mp3"), key=lambda file: file.stat().st_mtime, reverse=True)
            if not files:
                raise ValueError("YouTube Music did not produce an audio file.")
            info_files = list(Path(temporary).glob("*.info.json"))
            extracted = {}
            if info_files:
                try:
                    extracted = json.loads(info_files[0].read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    logger.warning("YouTube Music produced unreadable metadata for job #{}", job_id)
            artwork = None
            try:
                artwork_url = _download_artwork_url(track)
            except Exception as exc:
                artwork_url = None
                logger.warning("Could not resolve YouTube Music album artwork for job #{}: {}", job_id, exc)
            if artwork_url:
                try:
                    artwork = _fetch_artwork(artwork_url)
                except Exception as exc:
                    logger.warning("Could not fetch YouTube Music album artwork for job #{}: {}", job_id, exc)
            try:
                _write_download_tags(files[0], track, extracted, artwork)
            except Exception as exc:
                logger.error("Could not write YouTube Music metadata for job #{}: {}", job_id, exc)
                raise ValueError("YouTube Music audio was downloaded but its metadata could not be written.") from exc
            destination = output / files[0].name
            files[0].replace(destination)
            return destination
