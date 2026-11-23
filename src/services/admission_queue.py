"""Bounded FIFO wait for a free account slot.

When every eligible account is at its concurrency limit, requests wait here in
arrival order instead of failing at once. The wait is bounded in both length
and time; overflow raises an error that carries a Retry-After hint so callers
can answer HTTP 429.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Awaitable, Callable, Optional

# Seconds a rejected client should wait before retrying, by generation type:
# roughly how long one slot stays busy.
RETRY_AFTER_SECONDS = {"image": 10, "video": 30}
DEFAULT_RETRY_AFTER_SECONDS = 15


def retry_after_seconds(kind: str) -> int:
    return RETRY_AFTER_SECONDS.get(kind, DEFAULT_RETRY_AFTER_SECONDS)


class AdmissionRejected(Exception):
    """The request could not be admitted; answer HTTP 429 with Retry-After."""

    def __init__(self, reason: str, kind: str, waited_seconds: float = 0.0):
        super().__init__(reason)
        self.reason = reason  # "queue_full" or "queue_timeout"
        self.kind = kind
        self.waited_seconds = waited_seconds
        self.retry_after = retry_after_seconds(kind)


class AdmissionQueue:
    """Per-kind FIFO of requests waiting for a slot; only the head retries."""

    POLL_SECONDS = 0.2

    def __init__(
        self,
        max_waiting: Callable[[], int],
        wait_timeout: Callable[[str], float],
    ):
        self._max_waiting = max_waiting
        self._wait_timeout = wait_timeout
        self._waiters: dict[str, deque] = {}
        self._changed = asyncio.Event()

    def waiting(self, kind: str) -> int:
        return len(self._waiters.get(kind, ()))

    def is_full(self, kind: str) -> bool:
        return self.waiting(kind) >= max(0, int(self._max_waiting()))

    def notify(self) -> None:
        """Wake waiting requests after a slot was released."""
        changed, self._changed = self._changed, asyncio.Event()
        changed.set()

    async def wait_for_slot(
        self,
        kind: str,
        attempt: Callable[[], Awaitable[Any]],
        still_saturated: Callable[[], Awaitable[bool]],
    ) -> Any:
        """Wait in line until attempt() returns a result.

        Returns None when capacity is no longer the blocker (so the caller can
        report the real reason). Raises AdmissionRejected when the line is full
        or the wait exceeds its time limit.
        """
        if self.is_full(kind):
            raise AdmissionRejected("queue_full", kind)
        started = time.monotonic()
        deadline = started + max(1.0, float(self._wait_timeout(kind)))
        line = self._waiters.setdefault(kind, deque())
        ticket = object()
        line.append(ticket)
        try:
            while True:
                if line[0] is ticket:
                    result = await attempt()
                    if result is not None:
                        return result
                    if not await still_saturated():
                        return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AdmissionRejected(
                        "queue_timeout", kind, time.monotonic() - started
                    )
                changed = self._changed
                try:
                    await asyncio.wait_for(
                        changed.wait(), timeout=min(self.POLL_SECONDS, remaining)
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            try:
                line.remove(ticket)
            except ValueError:
                pass
            # The next in line should retry now rather than after a poll tick.
            self.notify()
