"""Run timer: monotonic server clock and gate crossings (CLAUDE.md §8.9)."""
from __future__ import annotations

import time

from ..geometry.lines import GateLine, crossing_fraction

Point2 = tuple[float, float]


class RunTimer:
    """Fed with every commanded segment; knows when the run started and ended.

    The crossing time is interpolated between the time stamps of the two
    points of the segment that crosses a gate.
    """

    def __init__(self, start_gate: GateLine, finish_gate: GateLine):
        self.start_gate, self.finish_gate = start_gate, finish_gate
        self.started_ns: int | None = None
        self.finished_ns: int | None = None

    @property
    def running(self) -> bool:
        return self.started_ns is not None and self.finished_ns is None

    def feed(self, p0: Point2, p1: Point2, t0_ns: int, t1_ns: int) -> str | None:
        """Returns "started", "finished" or None."""
        if self.finished_ns is not None:
            return None
        if self.started_ns is None:
            t = crossing_fraction(self.start_gate, p0, p1)
            if t is None:
                return None
            self.started_ns = int(t0_ns + t * (t1_ns - t0_ns))
            return "started"
        t = crossing_fraction(self.finish_gate, p0, p1)
        if t is None:
            return None
        self.finished_ns = max(self.started_ns, int(t0_ns + t * (t1_ns - t0_ns)))
        return "finished"

    def start_now(self, at_ns: int | None = None) -> None:
        self.started_ns = at_ns if at_ns is not None else time.monotonic_ns()

    def finish_now(self, at_ns: int | None = None) -> None:
        self.finished_ns = at_ns if at_ns is not None else time.monotonic_ns()

    def elapsed_ms(self, now_ns: int | None = None) -> int:
        if self.started_ns is None:
            return 0
        end = self.finished_ns if self.finished_ns is not None else (now_ns or time.monotonic_ns())
        return max(0, round((end - self.started_ns) / 1e6))

    @property
    def time_ms(self) -> int | None:
        return self.elapsed_ms() if self.finished_ns is not None else None


def format_time(time_ms: int) -> str:
    """`m:ss.cc`, e.g. 0:42.17."""
    cs = max(0, time_ms) // 10
    return f"{cs // 6000}:{(cs // 100) % 60:02d}.{cs % 100:02d}"
