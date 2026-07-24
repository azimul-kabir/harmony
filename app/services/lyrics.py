"""Extract bounded local lyrics from sidecar files and common audio tags."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_LYRICS_BYTES = 512 * 1024
MAX_LYRICS_CHARS = 200_000
SIDECAR_EXTENSIONS = (".lrc", ".txt")


@dataclass(frozen=True, slots=True)
class Lyrics:
    text: str
    source: str
    synchronized: bool


def extract_lyrics(audio_path: str | Path, tags: Any) -> Lyrics | None:
    path = Path(audio_path)
    for suffix in SIDECAR_EXTENSIONS:
        sidecar = path.with_suffix(suffix)
        if sidecar.is_file():
            text = _read_sidecar(sidecar)
            if text:
                return Lyrics(
                    text=text,
                    source=f"sidecar_{suffix[1:]}",
                    synchronized=suffix == ".lrc",
                )

    return _embedded_lyrics(tags)


def _read_sidecar(path: Path) -> str | None:
    if path.stat().st_size > MAX_LYRICS_BYTES:
        return None
    payload = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return _normalize(payload.decode(encoding))
        except UnicodeDecodeError:
            continue
    return None


def _embedded_lyrics(tags: Any) -> Lyrics | None:
    if tags is None:
        return None

    getall = getattr(tags, "getall", None)
    if getall:
        synced_frames = getall("SYLT")
        if synced_frames:
            values = getattr(synced_frames[0], "text", ())
            text = "\n".join(
                f"[{_lrc_timestamp(milliseconds)}]{line}"
                for line, milliseconds in values
                if str(line).strip()
            )
            normalized = _normalize(text)
            if normalized:
                return Lyrics(normalized, "embedded", True)

        unsynced_frames = getall("USLT")
        if unsynced_frames:
            normalized = _normalize(getattr(unsynced_frames[0], "text", ""))
            if normalized:
                return Lyrics(normalized, "embedded", False)

    for key, synchronized in (
        ("syncedlyrics", True),
        ("lyrics", False),
        ("unsyncedlyrics", False),
        ("\xa9lyr", False),
    ):
        value = tags.get(key) if hasattr(tags, "get") else None
        text = _first_text(value)
        normalized = _normalize(text)
        if normalized:
            return Lyrics(normalized, "embedded", synchronized)
    return None


def _first_text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "text"):
        value = value.text
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return value if isinstance(value, str) else str(value)


def _normalize(value: str) -> str | None:
    text = value.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text or len(text) > MAX_LYRICS_CHARS:
        return None
    return text


def _lrc_timestamp(milliseconds: int) -> str:
    total_centiseconds = max(0, int(milliseconds)) // 10
    minutes, remainder = divmod(total_centiseconds, 6000)
    seconds, centiseconds = divmod(remainder, 100)
    return f"{minutes:02d}:{seconds:02d}.{centiseconds:02d}"
