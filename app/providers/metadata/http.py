from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.core.logging import logger
from app.providers.metadata.errors import ProviderCancelledError, ProviderError
from app.providers.metadata.rate_limit import AsyncRateLimiter


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 3
    backoff_seconds: float = 0.5
    max_backoff_seconds: float = 10.0


class ProviderHttpClient:
    TRANSIENT = {408, 425, 429, 500, 502, 503, 504}

    def __init__(self, *, provider: str, base_url: str, user_agent: str, timeout: float,
                 retry: RetryPolicy, limiter: AsyncRateLimiter, max_concurrent: int,
                 transport: httpx.AsyncBaseTransport | None = None,
                 sleep=asyncio.sleep, random_fn: Callable[[], float] = random.random):
        if max_concurrent <= 0:
            raise ValueError("max_concurrent must be positive")
        self.provider, self.retry, self.limiter = provider, retry, limiter
        self._sleep, self._random = sleep, random_fn
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/") + "/", timeout=timeout,
            headers={"User-Agent": user_agent, "Accept": "application/json"}, transport=transport,
            limits=httpx.Limits(max_connections=max_concurrent, max_keepalive_connections=max_concurrent))
        self._closed = False

    async def get_json(self, path: str, *, params: dict, operation: str,
                       cancel_event: asyncio.Event | None = None) -> tuple[dict, int, float]:
        if self._closed:
            raise ProviderError("provider_closed", "Provider client is closed", provider=self.provider, operation=operation)
        retries = 0
        started = time.monotonic()
        while True:
            if cancel_event and cancel_event.is_set():
                raise ProviderCancelledError("cancelled", "Provider request cancelled", provider=self.provider, operation=operation)
            try:
                await self.limiter.acquire(cancel_event)
                async with self._semaphore:
                    request = asyncio.create_task(self._client.get(path, params=params))
                    if cancel_event is not None:
                        cancellation = asyncio.create_task(cancel_event.wait())
                        done, pending = await asyncio.wait({request, cancellation}, return_when=asyncio.FIRST_COMPLETED)
                        for task in pending: task.cancel()
                        if cancellation in done:
                            raise ProviderCancelledError("cancelled", "Provider request cancelled", provider=self.provider, operation=operation)
                    response = await request
                if response.status_code >= 400:
                    if response.status_code not in self.TRANSIENT or retries >= self.retry.max_retries:
                        code = "not_found" if response.status_code == 404 else "invalid_request" if response.status_code < 500 else "upstream_failure"
                        raise ProviderError(code, f"Provider returned HTTP {response.status_code}", provider=self.provider,
                            operation=operation, retryable=response.status_code in self.TRANSIENT, status_code=response.status_code)
                    retries += 1
                    await self._backoff(retries, response.headers.get("Retry-After"), cancel_event)
                    continue
                try: payload = response.json()
                except (ValueError, TypeError) as exc:
                    raise ProviderError("malformed_response", "Provider returned malformed JSON", provider=self.provider, operation=operation) from exc
                if not isinstance(payload, dict):
                    raise ProviderError("malformed_response", "Provider response was not an object", provider=self.provider, operation=operation)
                latency = (time.monotonic() - started) * 1000
                logger.info("provider={} operation={} latency_ms={:.1f} status={} retries={} cache_hit=false",
                    self.provider, operation, latency, response.status_code, retries)
                return payload, retries, latency
            except ProviderError:
                raise
            except asyncio.CancelledError as exc:
                raise ProviderCancelledError("cancelled", "Provider request cancelled", provider=self.provider, operation=operation) from exc
            except httpx.TimeoutException as exc:
                if retries >= self.retry.max_retries:
                    raise ProviderError("timeout", "Provider request timed out", provider=self.provider, operation=operation, retryable=True) from exc
                retries += 1
                await self._backoff(retries, None, cancel_event)
            except httpx.RequestError as exc:
                if retries >= self.retry.max_retries:
                    raise ProviderError("transport_failure", "Provider transport failed", provider=self.provider, operation=operation, retryable=True) from exc
                retries += 1
                await self._backoff(retries, None, cancel_event)

    async def _backoff(self, attempt: int, retry_after: str | None, cancel_event: asyncio.Event | None) -> None:
        try: delay = min(float(retry_after), self.retry.max_backoff_seconds) if retry_after else None
        except (TypeError, ValueError): delay = None
        if delay is None:
            delay = min(self.retry.backoff_seconds * (2 ** (attempt - 1)), self.retry.max_backoff_seconds)
            delay *= 0.5 + self._random()
        sleeper = asyncio.create_task(self._sleep(delay))
        if cancel_event is None:
            await sleeper; return
        cancelled = asyncio.create_task(cancel_event.wait())
        done, pending = await asyncio.wait({sleeper, cancelled}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending: task.cancel()
        if cancelled in done: raise ProviderCancelledError("cancelled", "Provider request cancelled", provider=self.provider, operation="retry_backoff")

    async def close(self) -> None:
        self._closed = True
        await self._client.aclose()
