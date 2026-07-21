from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class AsyncRateLimiter:
    """Shared, cancellation-friendly fixed-interval limiter with injectable time."""
    def __init__(self, requests_per_second: float, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self.interval = 1.0 / requests_per_second
        self._clock, self._sleep = clock, sleep
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self, cancel_event: asyncio.Event | None = None) -> None:
        async with self._lock:
            delay = max(0.0, self._next_at - self._clock())
            if delay:
                sleeper = asyncio.create_task(self._sleep(delay))
                if cancel_event is not None:
                    cancelled = asyncio.create_task(cancel_event.wait())
                    done, pending = await asyncio.wait({sleeper, cancelled}, return_when=asyncio.FIRST_COMPLETED)
                    for task in pending: task.cancel()
                    if cancelled in done:
                        raise asyncio.CancelledError
                else:
                    await sleeper
            self._next_at = max(self._clock(), self._next_at) + self.interval

    def status(self) -> dict:
        return {"requests_per_second": 1.0 / self.interval,
                "next_request_in_seconds": max(0.0, self._next_at - self._clock())}
