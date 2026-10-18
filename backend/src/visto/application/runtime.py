"""Standard-library clock and explicit cooperative execution controls."""

import asyncio
import time
from datetime import UTC, datetime, timedelta

from .ports import RunControl

# Some VM/container wall clocks are stepped backwards by host time sync (observed up
# to about a minute in a Windows Docker dev container). Evidence ordering and receipt
# validation need a non-decreasing clock, so wall time is anchored once per process
# and advanced by the monotonic clock.
_WALL_ANCHOR = datetime.now(UTC)
_MONOTONIC_ANCHOR = time.monotonic()


def utc_now() -> datetime:
    """Process-local UTC wall time that never moves backwards."""
    return _WALL_ANCHOR + timedelta(seconds=time.monotonic() - _MONOTONIC_ANCHOR)


class MutableRunControl:
    def __init__(self) -> None:
        self._cancelled = False
        self._paused = False

    def cancel(self) -> None:
        self._cancelled = True

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def cancel_requested(self) -> bool:
        return self._cancelled

    def pause_requested(self) -> bool:
        return self._paused


class SystemClock:
    def now(self) -> datetime:
        return utc_now()

    def monotonic(self) -> float:
        return time.monotonic()

    async def wait(self, delay_ms: int, control: RunControl) -> None:
        if type(delay_ms) is not int or delay_ms < 1:
            raise ValueError("Expected positive integer delay")
        deadline = self.monotonic() + delay_ms / 1000
        while not control.cancel_requested() and not control.pause_requested():
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                return
            await asyncio.sleep(min(remaining, 0.05))
