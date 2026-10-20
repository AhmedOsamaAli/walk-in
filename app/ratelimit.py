"""Per-client sliding-window rate limits for the public demo."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request


class RateLimiter:
    def __init__(self, limit: int, window_s: int) -> None:
        self.limit, self.window_s = limit, window_s
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


def client_ip(request: Request) -> str:
    # The hosting proxy appends the address it saw, so the last entry cannot be forged by the client.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"
