"""Sliding-window counters for rate limits and budgets."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable


class InMemoryQuota:
    """Per key deque of ``(timestamp, amount)``.

    Entries older than the window passed to a call are dropped on that call, so use one
    window per key (the runtime does: 60 s for rate limits, 86400 s for budgets).
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._events: dict[str, deque[tuple[float, float]]] = {}
        self._lock = asyncio.Lock()

    def _total(self, key: str, window_s: float) -> float:
        events = self._events.get(key)
        if events is None:
            return 0.0
        cutoff = self._clock() - window_s
        while events and events[0][0] <= cutoff:
            events.popleft()
        if not events:
            del self._events[key]
            return 0.0
        return sum(amount for _, amount in events)

    async def add(self, key: str, amount: float, *, window_s: float) -> float:
        async with self._lock:
            self._total(key, window_s)
            self._events.setdefault(key, deque()).append((self._clock(), amount))
            return self._total(key, window_s)

    async def usage(self, key: str, *, window_s: float) -> float:
        async with self._lock:
            return self._total(key, window_s)
