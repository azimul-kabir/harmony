"""Explainable, read-only duplicate detection over the Library Index."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from pathlib import Path
import re
import unicodedata
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Song
from app.services.library_catalog import serialize_song_page, with_song_artwork


TIERS = ("exact", "strong", "probable", "possible")
TIER_RANK = {tier: index for index, tier in enumerate(TIERS)}
MAX_BUCKET_SIZE = 100


def is_duplicate(destination: Path) -> bool:
    """Keep the downloader's existing destination collision safeguard."""
    return destination.exists()


def _normal(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return " ".join(re.findall(r"[^\W_]+", value, flags=re.UNICODE))


def _external_conflict(left: Song, right: Song) -> bool:
    fields = ("musicbrainz_recording_id", "isrc", "spotify_track_id")
    return any(
        getattr(left, field) and getattr(right, field)
        and _normal(getattr(left, field)) != _normal(getattr(right, field))
        for field in fields
    )


def _quality(song: Song) -> tuple[int, int, int, int, int]:
    metadata = sum(bool(getattr(song, field)) for field in (
        "title", "artist", "album", "year", "genre", "isrc",
        "musicbrainz_recording_id",
    ))
    return (
        1 if song.availability_status == "available" else 0,
        song.bitrate or 0,
        song.sample_rate or 0,
        song.file_size or 0,
        metadata,
    )


def _group_id(song_ids: list[int]) -> str:
    digest = sha256(",".join(map(str, sorted(song_ids))).encode()).hexdigest()[:16]
    return f"dup-{digest}"


class DuplicateDetector:
    def _songs(self, db: Session, include_missing: bool) -> list[Song]:
        query = select(Song).order_by(Song.id)
        if not include_missing:
            query = query.where(Song.availability_status == "available")
        return list(db.scalars(with_song_artwork(query)).unique().all())

    def detect(self, db: Session, *, include_missing: bool = False) -> list[dict[str, Any]]:
        songs = self._songs(db, include_missing)
        by_id = {song.id: song for song in songs}
        serialized_by_id = {
            item["id"]: item for item in serialize_song_page(db, songs)
        }
        parent = {song.id: song.id for song in songs}
        evidence: dict[frozenset[int], dict[str, Any]] = {}

        def find(song_id: int) -> int:
            while parent[song_id] != song_id:
                parent[song_id] = parent[parent[song_id]]
                song_id = parent[song_id]
            return song_id

        def connect(left: Song, right: Song, tier: str, field: str, message: str) -> None:
            left_root, right_root = find(left.id), find(right.id)
            if left_root != right_root:
                parent[right_root] = left_root
            key = frozenset((left.id, right.id))
            previous = evidence.get(key)
            if previous is None or TIER_RANK[tier] < TIER_RANK[previous["tier"]]:
                evidence[key] = {"tier": tier, "field": field, "message": message}

        for field, tier, label in (
            ("musicbrainz_recording_id", "exact", "MusicBrainz recording ID"),
            ("isrc", "strong", "ISRC"),
            ("spotify_track_id", "exact", "Spotify track ID"),
        ):
            buckets: dict[str, list[Song]] = defaultdict(list)
            for song in songs:
                value = _normal(getattr(song, field))
                if value:
                    buckets[value].append(song)
            for bucket in buckets.values():
                if len(bucket) < 2:
                    continue
                for index, left in enumerate(bucket):
                    for right in bucket[index + 1:]:
                        connect(left, right, tier, field, f"Same {label}")

        title_artist: dict[tuple[str, str], list[Song]] = defaultdict(list)
        for song in songs:
            key = (_normal(song.artist), _normal(song.title))
            if all(key):
                title_artist[key].append(song)
        for bucket in title_artist.values():
            if len(bucket) < 2 or len(bucket) > MAX_BUCKET_SIZE:
                continue
            for index, left in enumerate(bucket):
                for right in bucket[index + 1:]:
                    if _external_conflict(left, right):
                        continue
                    same_album = bool(_normal(left.album)) and _normal(left.album) == _normal(right.album)
                    if left.duration is not None and right.duration is not None:
                        delta = abs(left.duration - right.duration)
                        if delta <= 3:
                            connect(left, right, "probable", "artist_title_duration",
                                    f"Same normalized artist/title; duration differs by {delta:.1f}s")
                        elif same_album and delta <= 10:
                            connect(left, right, "possible", "artist_title_album_duration",
                                    f"Same normalized artist/title/album; duration differs by {delta:.1f}s")
                    elif same_album:
                        connect(left, right, "possible", "artist_title_album",
                                "Same normalized artist/title/album; duration comparison unavailable")

        members: dict[int, list[int]] = defaultdict(list)
        for song_id in parent:
            members[find(song_id)].append(song_id)
        groups = []
        for song_ids in members.values():
            if len(song_ids) < 2:
                continue
            group_edges = [
                item for pair, item in evidence.items() if pair.issubset(song_ids)
            ]
            # A connected group is only as confident as the weakest edge
            # required to explain all of its members.
            tier = max((item["tier"] for item in group_edges), key=TIER_RANK.__getitem__)
            ordered = sorted((by_id[song_id] for song_id in song_ids), key=_quality, reverse=True)
            keeper = ordered[0]
            groups.append({
                "id": _group_id(song_ids),
                "tier": tier,
                "confidence": {"exact": 1.0, "strong": 0.95, "probable": 0.8, "possible": 0.6}[tier],
                "song_ids": sorted(song_ids),
                "song_count": len(song_ids),
                "recommended_keep_id": keeper.id,
                "recommendation_reasons": [
                    "Available file preferred" if keeper.availability_status == "available" else "Only indexed candidate",
                    f"Highest quality score: {keeper.bitrate or 0} bps, {keeper.sample_rate or 0} Hz",
                ],
                "evidence": sorted(group_edges, key=lambda item: (TIER_RANK[item["tier"]], item["field"])),
                "songs": [serialized_by_id[song.id] for song in ordered],
            })
        return sorted(groups, key=lambda group: (TIER_RANK[group["tier"]], -group["song_count"], group["id"]))

    def list(self, db: Session, *, tier: str | None = None, include_missing: bool = False,
             limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if tier is not None and tier not in TIERS:
            raise ValueError("Unsupported duplicate tier")
        groups = self.detect(db, include_missing=include_missing)
        if tier:
            groups = [group for group in groups if group["tier"] == tier]
        page = groups[offset:offset + limit]
        return {
            "items": page,
            "total": len(groups),
            "duplicate_songs": sum(item["song_count"] for item in groups),
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(page) < len(groups),
        }

    def get(self, db: Session, group_id: str, *, include_missing: bool = False) -> dict[str, Any] | None:
        return next(
            (group for group in self.detect(db, include_missing=include_missing) if group["id"] == group_id),
            None,
        )


duplicate_detector = DuplicateDetector()
