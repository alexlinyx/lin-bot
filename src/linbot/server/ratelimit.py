"""Per-client sliding-window rate limiter.

In-process on purpose: with a single always-on instance this is exact, free,
and has no infrastructure. If the service ever runs multiple replicas, this is
the seam to swap for a shared store (e.g. Redis).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, client_id: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        hits = self._hits[client_id]
        cutoff = now - self.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True
