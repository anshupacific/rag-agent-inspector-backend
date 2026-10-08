"""Spend protection: a per-visitor limit per minute and a daily cap for the whole API.

Counters live in memory, which is correct for a single App Service instance
running one worker. Move them to a shared store before scaling out.
"""

import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone


class RateLimitExceeded(Exception):
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after


class RateLimiter:
    def __init__(self, per_minute: int, per_day: int):
        self.per_minute = per_minute
        self.per_day = per_day
        self._lock = threading.Lock()
        self._recent = defaultdict(deque)  # visitor -> timestamps in the last minute
        self._day = None
        self._day_count = 0

    def check(self, visitor: str) -> None:
        """Record one request, or raise RateLimitExceeded."""
        now = time.monotonic()
        today = datetime.now(timezone.utc).date()
        with self._lock:
            if today != self._day:
                self._day, self._day_count = today, 0
                self._recent.clear()
            if self._day_count >= self.per_day:
                raise RateLimitExceeded("The demo has reached its daily limit. Try again tomorrow.", 3600)

            window = self._recent[visitor]
            while window and now - window[0] >= 60:
                window.popleft()
            if len(window) >= self.per_minute:
                wait = int(60 - (now - window[0])) + 1
                raise RateLimitExceeded("Too many questions. Wait a moment and try again.", wait)

            window.append(now)
            self._day_count += 1
