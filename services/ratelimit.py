"""Sliding-window rate limiting per client, kept in memory (this app runs as a single process)."""
import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit, window_seconds):
        self.limit = limit
        self.window = window_seconds
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key):
        """Records a hit. Returns 0 when allowed, otherwise seconds until the next slot frees up."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return int(self.window - (now - hits[0])) + 1
            hits.append(now)
            return 0

    def reset(self):
        with self._lock:
            self._hits.clear()
