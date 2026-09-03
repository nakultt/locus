"""
A sliding-window counter, for throttling repeated failures.

Written rather than pulled in because the one thing it is used for — stopping
unlimited password guesses against a known email — needs no storage backend, no
middleware and no configuration, and every off-the-shelf limiter brings all
three.

**This counter is per process.** Two workers behind a load balancer each hold
their own window, so the effective allowance is the configured one multiplied by
the number of processes. That is a real weakening and it is stated here rather
than hidden: it takes unlimited guessing down to a bounded rate, which is the
whole point, and the repository already notes that multi-instance deployment is
guarded but unproven. A shared store is the right answer the day this runs on
more than one instance.

Nothing here is keyed by IP. See `app/routers/auth.py` for why.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

# Windows are small and bounded, so a plain dict of deques is enough. The lock
# matters because uvicorn runs sync endpoints on a threadpool: two failed logins
# for the same account can land on different threads at the same moment, and an
# unsynchronised deque loses one of them.
_events: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()

# Buckets are dropped once they fall out of their own window, so an attacker
# cannot grow this dict without bound by cycling through addresses — but a
# bucket is only visited when its key is used again, so a sweep runs
# occasionally to collect the ones nobody comes back to.
_MAX_TRACKED = 10_000


def _prune(events: deque[float], now: float, window: float) -> None:
    while events and events[0] <= now - window:
        events.popleft()


def count(key: str, window_seconds: float) -> int:
    """How many events are recorded for `key` inside the window."""
    now = time.monotonic()
    with _lock:
        events = _events[key]
        _prune(events, now, window_seconds)
        if not events:
            # Never leave an empty deque behind: that is how this dict would
            # grow one entry per email anybody ever guessed at.
            _events.pop(key, None)
            return 0
        return len(events)


def record(key: str, window_seconds: float) -> int:
    """Record one event against `key`, returning the new count in the window."""
    now = time.monotonic()
    with _lock:
        if len(_events) > _MAX_TRACKED:
            _sweep(now, window_seconds)
        events = _events[key]
        _prune(events, now, window_seconds)
        events.append(now)
        return len(events)


def retry_after(key: str, window_seconds: float) -> int:
    """
    Seconds until the oldest event in the window expires.

    This is what a caller is told to wait, so it is the *oldest* event rather
    than the newest: that is the moment one slot frees up and another attempt
    becomes possible.
    """
    now = time.monotonic()
    with _lock:
        events = _events.get(key)
        if not events:
            return 0
        return max(1, int(events[0] + window_seconds - now) + 1)


def clear(key: str | None = None) -> None:
    """
    Forget one key, or all of them.

    Called on a *successful* login, so an account that was being guessed at
    stops carrying that history the moment its real owner gets in.
    """
    with _lock:
        if key is None:
            _events.clear()
        else:
            _events.pop(key, None)


def _sweep(now: float, window_seconds: float) -> None:
    """Drop every bucket whose events have all expired. Caller holds the lock."""
    for key in list(_events):
        events = _events[key]
        _prune(events, now, window_seconds)
        if not events:
            del _events[key]
