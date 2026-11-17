"""A small in-process sliding-window limiter for public and costly endpoints.

The demo runs as one process, so memory is enough. Keys are hashed so raw IP
addresses are never kept (section 5, K7: no IP storage for anonymous flows).
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import deque

from fastapi import Request

from .accounts.router import ApiError


class RateLimiter:
    def __init__(self, limit: int, window: float) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, now: float | None = None) -> float | None:
        """Record a hit; returns seconds to wait when over the limit, else None."""
        now = time.monotonic() if now is None else now
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        with self._lock:
            queue = self._hits.setdefault(digest, deque())
            while queue and queue[0] <= now - self.window:
                queue.popleft()
            if len(queue) >= self.limit:
                return max(1.0, queue[0] + self.window - now)
            queue.append(now)
            if len(self._hits) > 50_000:  # bound memory under a flood
                self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > now - self.window}
            return None

    def check(self, request: Request, scope: str, subject: str | None = None) -> None:
        client = request.client.host if request.client else "unknown"
        wait = self.hit(f"{scope}|{subject or client}")
        if wait is not None:
            raise ApiError(429, "rate_limited", "Слишком много запросов. Подождите немного и повторите.",
                           headers={"Retry-After": str(int(wait) + 1)})
