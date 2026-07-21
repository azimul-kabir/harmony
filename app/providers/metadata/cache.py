from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select

from app.core.time import utcnow_naive
from app.database.models import ProviderCacheEntry
from app.database.session import SessionLocal


@dataclass(frozen=True)
class CacheResult:
    data: dict | None
    stale: bool = False


class ProviderCache:
    def __init__(self, provider: str, ttl_seconds: int, provider_version: str):
        self.provider, self.ttl_seconds, self.provider_version = provider, ttl_seconds, provider_version
        self._hits = self._misses = self._bypasses = 0
        self._lock = threading.Lock()

    @staticmethod
    def key(lookup_type: str, *, query: str | None = None, entity_id: str | None = None,
            limit: int | None = None, offset: int | None = None) -> str:
        value = json.dumps({"type": lookup_type, "query": query, "entity_id": entity_id,
                            "limit": limit, "offset": offset}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(value.encode()).hexdigest()

    def get(self, cache_key: str, *, allow_stale: bool = False, bypass: bool = False) -> CacheResult:
        if bypass:
            with self._lock: self._bypasses += 1
            return CacheResult(None)
        db = SessionLocal()
        try:
            row = db.scalar(select(ProviderCacheEntry).where(
                ProviderCacheEntry.provider == self.provider,
                ProviderCacheEntry.cache_key == cache_key,
                ProviderCacheEntry.provider_version == self.provider_version,
            ))
            stale = bool(row and row.expires_at <= utcnow_naive())
            if row and (allow_stale or not stale):
                try: data = json.loads(row.normalized_data)
                except (TypeError, json.JSONDecodeError): data = None
                if data is not None:
                    with self._lock: self._hits += 1
                    return CacheResult(data, stale)
            with self._lock: self._misses += 1
            return CacheResult(None, stale)
        finally:
            db.close()

    def put(self, cache_key: str, lookup_type: str, data: dict, *, query: str | None = None,
            entity_id: str | None = None) -> None:
        now = utcnow_naive()
        db = SessionLocal()
        try:
            row = db.scalar(select(ProviderCacheEntry).where(
                ProviderCacheEntry.provider == self.provider,
                ProviderCacheEntry.cache_key == cache_key,
            ))
            if row is None:
                row = ProviderCacheEntry(provider=self.provider, cache_key=cache_key, lookup_type=lookup_type,
                    query=query, entity_id=entity_id, normalized_data="", fetched_at=now,
                    expires_at=now, provider_version=self.provider_version)
                db.add(row)
            row.lookup_type, row.query, row.entity_id = lookup_type, query, entity_id
            row.normalized_data = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            row.fetched_at, row.expires_at = now, now + timedelta(seconds=self.ttl_seconds)
            row.provider_version = self.provider_version
            db.commit()
        finally:
            db.close()

    def clear_expired(self) -> int:
        db = SessionLocal()
        try:
            result = db.execute(delete(ProviderCacheEntry).where(
                ProviderCacheEntry.provider == self.provider,
                ProviderCacheEntry.expires_at <= utcnow_naive()))
            db.commit()
            return result.rowcount or 0
        finally: db.close()

    def stats(self) -> dict:
        now = utcnow_naive()
        db = SessionLocal()
        try:
            total = db.scalar(select(func.count()).select_from(ProviderCacheEntry).where(
                ProviderCacheEntry.provider == self.provider)) or 0
            stale = db.scalar(select(func.count()).select_from(ProviderCacheEntry).where(
                ProviderCacheEntry.provider == self.provider, ProviderCacheEntry.expires_at <= now)) or 0
        finally: db.close()
        with self._lock: runtime = {"hits": self._hits, "misses": self._misses, "bypasses": self._bypasses}
        return {**runtime, "entries": total, "fresh_entries": total - stale, "stale_entries": stale,
                "ttl_seconds": self.ttl_seconds}
