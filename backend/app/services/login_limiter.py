"""In-process failed-login limiter (guide 05 §2: one API worker for the local demo).

Counts failures per normalized email and per client address in a sliding window. Multiple
workers would each hold their own counts; coordinate (e.g. shared store) before scaling out.
"""

import threading
import time
from collections import defaultdict, deque

from app.core.config import get_settings


class LoginLimiter:
    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float, window: int) -> deque[float]:
        q = self._failures[key]
        while q and q[0] <= now - window:
            q.popleft()
        return q

    def retry_after(self, keys: list[str]) -> int | None:
        """Seconds until another attempt is allowed, or None if allowed now."""
        s = get_settings()
        now = time.monotonic()
        with self._lock:
            waits = []
            for k in keys:
                q = self._prune(k, now, s.LOGIN_WINDOW_SECONDS)
                if len(q) >= s.LOGIN_MAX_FAILURES:
                    waits.append(int(q[0] + s.LOGIN_WINDOW_SECONDS - now) + 1)
            return max(waits) if waits else None

    def record_failure(self, keys: list[str]) -> None:
        now = time.monotonic()
        with self._lock:
            for k in keys:
                self._failures[k].append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


limiter = LoginLimiter()
