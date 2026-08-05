from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic_ns

from .models import MIN_INTERVAL_NS


class WeightedPacer:
    """Reserve REST request start times using documented rate-limit weights."""

    __slots__ = ("_clock_ns", "_interval_ns", "_next_start_ns", "_sleep")

    def __init__(
        self,
        *,
        interval_ns: int = MIN_INTERVAL_NS,
        clock_ns: Callable[[], int] = monotonic_ns,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if interval_ns < MIN_INTERVAL_NS:
            raise ValueError(f"interval_ns must be at least {MIN_INTERVAL_NS}")
        self._interval_ns = interval_ns
        self._clock_ns = clock_ns
        self._sleep = sleep
        self._next_start_ns: int | None = None

    async def wait(self, weight: int = 1) -> None:
        if isinstance(weight, bool) or not isinstance(weight, int) or weight < 1:
            raise ValueError("weight must be a positive integer")

        now = self._clock_ns()
        if self._next_start_ns is not None and now < self._next_start_ns:
            await self._sleep((self._next_start_ns - now) / 1_000_000_000)
            now = self._clock_ns()
        self._next_start_ns = max(now, self._next_start_ns or now) + (
            self._interval_ns * weight
        )
