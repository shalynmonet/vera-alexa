"""A small in-memory rate limiter for the calls that cost real money per
request (Bedrock chat/greet, Polly speech) -- two layers per limiter, a
per-device cap (one person spamming the mic can't run up the bill alone)
and a global cap (a hard ceiling on total spend even if many devices hit
it at once, intentionally or not).

In-memory and per-process by design: this app runs as a single systemd
service, not a multi-worker/multi-instance deployment, so there's nothing
to share across processes and no reason to add a Redis dependency for it.
If that ever changes, swap this for a shared store without touching any
call site -- same reasoning as vera/storage.py's Store abstraction.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, per_device_limit: int, per_device_window: float, global_limit: int, global_window: float):
        self.per_device_limit = per_device_limit
        self.per_device_window = per_device_window
        self.global_limit = global_limit
        self.global_window = global_window
        self._device_hits: dict[str, deque] = defaultdict(deque)
        self._global_hits: deque = deque()

    @staticmethod
    def _prune(hits: deque, window: float, now: float) -> None:
        cutoff = now - window
        while hits and hits[0] < cutoff:
            hits.popleft()

    def allow(self, device_id: str) -> bool:
        now = time.monotonic()
        self._prune(self._global_hits, self.global_window, now)
        if len(self._global_hits) >= self.global_limit:
            return False
        device_hits = self._device_hits[device_id]
        self._prune(device_hits, self.per_device_window, now)
        if len(device_hits) >= self.per_device_limit:
            return False
        device_hits.append(now)
        self._global_hits.append(now)
        return True


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# Chat covers both /api/chat and /api/greet (both call Bedrock). Speak
# covers /api/speak (Polly). Windows are in seconds; one minute each.
chat_limiter = RateLimiter(
    per_device_limit=_int_env("VERA_RATE_LIMIT_CHAT_PER_DEVICE", 20),
    per_device_window=60,
    global_limit=_int_env("VERA_RATE_LIMIT_CHAT_GLOBAL", 200),
    global_window=60,
)
speak_limiter = RateLimiter(
    per_device_limit=_int_env("VERA_RATE_LIMIT_SPEAK_PER_DEVICE", 40),
    per_device_window=60,
    global_limit=_int_env("VERA_RATE_LIMIT_SPEAK_GLOBAL", 400),
    global_window=60,
)
