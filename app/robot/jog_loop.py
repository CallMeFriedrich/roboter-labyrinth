"""Keys → target points (CLAUDE.md §8.4).

The loop never has more than one command on its way: the next step is only
sent after the answer to the previous one. The step length follows the
measured cycle time, so the speed stays constant even if the robot answers
slower than the nominal rate.
"""
from __future__ import annotations

import asyncio
import math
import time
from typing import Awaitable, Callable

Point2 = tuple[float, float]
KEY_VECTORS = {"w": (0, -1), "s": (0, 1), "a": (-1, 0), "d": (1, 0)}
HEARTBEAT_TIMEOUT = 0.3     # s without heartbeat → all keys count as released


def direction(keys) -> Point2:
    """d = (D − A, S − W), normalised: diagonals are as fast as straight moves."""
    dx = sum(KEY_VECTORS[k][0] for k in keys if k in KEY_VECTORS)
    dy = sum(KEY_VECTORS[k][1] for k in keys if k in KEY_VECTORS)
    length = math.hypot(dx, dy)
    return (0.0, 0.0) if length == 0 else (dx / length, dy / length)


class KeyState:
    """Pressed keys with dead man's logic."""

    def __init__(self, timeout: float = HEARTBEAT_TIMEOUT, clock: Callable[[], float] = time.monotonic):
        self._down: frozenset[str] = frozenset()
        self._stamp = 0.0
        self._timeout = timeout
        self._clock = clock

    def update(self, down) -> None:
        self._down = frozenset(k for k in down if k in KEY_VECTORS)
        self._stamp = self._clock()

    def clear(self) -> None:
        self._down = frozenset()

    def active(self) -> frozenset[str]:
        if self._down and self._clock() - self._stamp > self._timeout:
            self._down = frozenset()
        return self._down


class JogLoop:
    """Runs until `stop()` is called. All coordinates are plate x/y."""

    def __init__(self, *, start: Point2, keys: Callable[[], frozenset[str]],
                 constrain: Callable[[Point2, Point2], Point2],
                 move: Callable[[Point2], Awaitable[None]],
                 on_segment: Callable[[Point2, Point2, int, int], None],
                 speed: Callable[[], float], rate_hz: Callable[[], float]):
        self.position = start
        self._keys, self._constrain, self._move = keys, constrain, move
        self._on_segment, self._speed, self._rate = on_segment, speed, rate_hz
        self._stopped = False
        self.cycle_ms = 0.0

    def stop(self) -> None:
        self._stopped = True

    async def run(self) -> None:
        last_step_end: float | None = None      # None → the robot stands still
        last_stamp_ns = time.monotonic_ns()
        while not self._stopped:
            period = 1.0 / self._rate()
            tick = time.monotonic()
            d = direction(self._keys())
            if d == (0.0, 0.0):
                last_step_end = None
            else:
                # Distance for the time since the previous step was sent; capped
                # so that a slow answer cannot produce one huge step.
                dt = period if last_step_end is None else min(tick - last_step_end, 2.0 * period)
                dt = max(dt, 0.5 * period)
                step = self._speed() * dt
                target = (self.position[0] + d[0] * step, self.position[1] + d[1] * step)
                target = self._constrain(self.position, target)
                if target != self.position:
                    last_step_end = tick
                    await self._move(target)
                    stamp_ns = time.monotonic_ns()
                    previous, self.position = self.position, target
                    self._on_segment(previous, target, last_stamp_ns, stamp_ns)
                    last_stamp_ns = stamp_ns
                    self.cycle_ms = (time.monotonic() - tick) * 1000.0
                else:
                    last_step_end = None
            if d == (0.0, 0.0) or last_step_end is None:
                last_stamp_ns = time.monotonic_ns()
            rest = period - (time.monotonic() - tick)
            await asyncio.sleep(rest if rest > 0 else 0)
