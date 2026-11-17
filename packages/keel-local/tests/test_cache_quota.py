from __future__ import annotations

import asyncio

from keel_core.ports import Completion, Principal
from keel_local.cache import InMemoryCache
from keel_local.quota import InMemoryQuota


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


A = Principal("a", tenant="t1")
B = Principal("b", tenant="t1")
A2 = Principal("a", tenant="t2")
C = Completion("hi", 1, 1)


def test_cache_scoped_per_user_and_tenant() -> None:
    cache = InMemoryCache()

    async def run() -> list[Completion | None]:
        await cache.put("k", C, principal=A)
        return [
            await cache.get("k", principal=A),
            await cache.get("k", principal=B),
            await cache.get("k", principal=A2),
            await cache.get("other", principal=A),
        ]

    assert asyncio.run(run()) == [C, None, None, None]


def test_cache_ttl_and_lru() -> None:
    clock = Clock()
    cache = InMemoryCache(ttl_s=10, max_entries=2, clock=clock)

    async def run() -> None:
        await cache.put("a", C, principal=A)
        await cache.put("b", C, principal=A)
        assert await cache.get("a", principal=A) == C  # a is now most recent
        await cache.put("c", C, principal=A)  # evicts b
        assert await cache.get("b", principal=A) is None
        assert await cache.get("a", principal=A) == C
        clock.now += 11
        assert await cache.get("a", principal=A) is None

    asyncio.run(run())


def test_quota_sliding_window() -> None:
    clock = Clock()
    quota = InMemoryQuota(clock=clock)

    async def run() -> None:
        assert await quota.usage("k", window_s=60) == 0
        assert await quota.add("k", 1, window_s=60) == 1
        clock.now += 30
        assert await quota.add("k", 2.5, window_s=60) == 3.5
        assert await quota.usage("k", window_s=60) == 3.5
        clock.now += 31  # first entry is 61s old
        assert await quota.usage("k", window_s=60) == 2.5
        clock.now += 60
        assert await quota.usage("k", window_s=60) == 0
        assert await quota.add("other", 1, window_s=60) == 1

    asyncio.run(run())
