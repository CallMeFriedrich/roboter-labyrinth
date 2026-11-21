"""Driver interface shared by simulator, standard and extended driver (CLAUDE.md §8.1)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Sequence

from ..geometry.frames import IDENTITY_QUAT, Frame

log = logging.getLogger("robot")


class DriverError(Exception):
    """Connection lost or the controller refused a command."""


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    z: float
    q: tuple[float, float, float, float] = IDENTITY_QUAT

    @property
    def xyz(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    def with_xyz(self, x: float, y: float, z: float) -> "Pose":
        return Pose(x, y, z, self.q)


@dataclass(frozen=True)
class RobotInfo:
    serial: str = ""
    robotware: str = ""
    robot_type: str = ""


# Guard: called with (pose, speed) before every Cartesian move; raises ValueError.
Guard = Callable[[Pose, float], None]
ProgressCallback = Callable[[tuple[float, float, float]], None]


class RobotDriver:
    """Base class. All moves are in the currently configured work object."""

    name = "base"

    def __init__(self) -> None:
        self.guard: Guard | None = None
        self.latency_ms: float = 0.0

    def _check(self, pose: Pose, speed: float) -> None:
        if self.guard is None:
            return
        try:
            self.guard(pose, speed)
        except ValueError as exc:
            log.warning("Fahrbefehl abgelehnt: %s (Ziel %.1f/%.1f/%.1f, %.0f mm/s)",
                        exc, pose.x, pose.y, pose.z, speed)
            raise

    @property
    def connected(self) -> bool:
        raise NotImplementedError

    async def connect(self) -> None:
        raise NotImplementedError

    async def disconnect(self) -> None:
        raise NotImplementedError

    async def ping(self) -> None:
        raise NotImplementedError

    async def configure(self, tool: Frame, wobj: Frame, speed: float, zone: str) -> None:
        """Must be called after every (re)connect: the controller forgets these values."""
        raise NotImplementedError

    async def move_linear(self, pose: Pose, speed: float, zone: str) -> None:
        raise NotImplementedError

    async def move_joints(self, joints: Sequence[float], speed: float) -> None:
        raise NotImplementedError

    async def get_pose(self) -> Pose:
        raise NotImplementedError

    async def get_joints(self) -> list[float]:
        raise NotImplementedError

    async def run_path(self, poses: Sequence[Pose], speed: float, zone: str,
                       on_progress: ProgressCallback | None = None) -> None:
        """Drive through all poses without stopping in between (blocks until done)."""
        raise NotImplementedError

    async def info(self) -> RobotInfo:
        raise NotImplementedError

    def actual_position(self) -> tuple[float, float, float] | None:
        """Measured position in the work object, if the driver has one (else None)."""
        return None

    @property
    def has_actual_position(self) -> bool:
        return False
