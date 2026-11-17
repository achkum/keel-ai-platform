"""In-memory response cache, scoped per user and tenant."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable

from keel_core.ports import Completion, Principal


class InMemoryCache:
    """TTL plus LRU cache.

    Entries are keyed by tenant, user and request key, so one user never sees another's
    answer. The spec's ``semantic`` mode uses this same exact-match cache in local mode;
    embedding based matching needs a vector store and comes with a later adapter.
    """

    def __init__(
        self,
        *,
        ttl_s: float = 3600.0,
        max_entries: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_s
        self._max = max_entries
        self._clock = clock
        self._data: OrderedDict[tuple[str, str, str], tuple[float, Completion]] = OrderedDict()

    @staticmethod
    def _key(key: str, principal: Principal) -> tuple[str, str, str]:
        return (principal.tenant or "", principal.user_id, key)

    async def get(self, key: str, *, principal: Principal) -> Completion | None:
        k = self._key(key, principal)
        item = self._data.get(k)
        if item is None:
            return None
        stored_at, value = item
        if self._clock() - stored_at > self._ttl:
            del self._data[k]
            return None
        self._data.move_to_end(k)
        return value

    async def put(self, key: str, value: Completion, *, principal: Principal) -> None:
        k = self._key(key, principal)
        self._data[k] = (self._clock(), value)
        self._data.move_to_end(k)
        while len(self._data) > self._max:
            self._data.popitem(last=False)
