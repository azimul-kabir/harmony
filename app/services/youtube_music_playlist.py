"""Batched, metadata-only public YouTube Music playlist reader."""

from dataclasses import dataclass
from typing import Iterator

from app.domain.track import Track
from app.providers.youtube_music import YouTubeMusicSource, clean_title, watch_url


@dataclass(frozen=True, slots=True)
class YouTubeMusicPlaylistMetadata:
    name: str
    url: str


class YouTubeMusicPlaylistReader:
    def __init__(self, url: str, batch_size: int = 50) -> None:
        self.url = url
        self.batch_size = batch_size
        self.source = YouTubeMusicSource()
        self._data: dict | None = None
        self.skipped_count = 0

    def _extract(self) -> dict:
        if self._data is None:
            self._data = self.source._run_json(self.url, flat=True)
        return self._data

    def metadata(self) -> YouTubeMusicPlaylistMetadata:
        data = self._extract()
        return YouTubeMusicPlaylistMetadata(
            name=clean_title(data.get("title")) or "YouTube Music Playlist",
            url=self.url,
        )

    def batches(self) -> Iterator[list[Track]]:
        pending: list[Track] = []
        seen: set[str] = set()
        for entry in self._extract().get("entries") or []:
            if not entry or entry.get("availability") in {"private", "premium_only", "subscriber_only"}:
                self.skipped_count += 1
                continue
            item_id = str(entry.get("id") or entry.get("url") or "").strip()
            title = clean_title(entry.get("track") or entry.get("title"))
            if not item_id or not title or item_id in seen:
                self.skipped_count += 1
                continue
            seen.add(item_id)
            artist = entry.get("artist") or entry.get("uploader") or entry.get("channel") or "Unknown Artist"
            if artist.endswith(" - Topic"):
                artist = artist[:-8]
            pending.append(Track(
                title=title,
                artist=artist,
                album=entry.get("album") or self._data.get("title"),
                duration=entry.get("duration"),
                source_provider="youtube_music",
                source_item_id=item_id,
                source_url=watch_url(item_id),
            ))
            if len(pending) == self.batch_size:
                yield pending
                pending = []
        if pending:
            yield pending
