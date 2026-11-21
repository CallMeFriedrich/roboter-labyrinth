"""Simulator driver: no robot needed, same timing semantics as SERVER.mod (CLAUDE.md §8.3)."""
from __future__ import annotations

import asyncio
from typing import Sequence

from ..geometry.frames import Frame
from .driver_base import DriverError, Pose, ProgressCallback, RobotDriver, RobotInfo
from .motion_model import MotionModel
from .protocol import zone_radius


class SimDriver(RobotDriver):
    name = "sim"

    def __init__(self, acceleration: float = 1000.0, latency_ms: float = 15.0,
                 home_position=(374.0, 0.0, 420.0), time_scale: float = 1.0):
        super().__init__()
        self.model = MotionModel(acceleration, tuple(home_position), time_scale)
        self.latency_ms = latency_ms
        self._time_scale = time_scale
        self._connected = False
        self._lock = asyncio.Lock()      # the real protocol is strictly sequential
        self.fail_next = False           # test hook: next command raises DriverError

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def _latency(self) -> None:
        if not self._connected:
            raise DriverError("Simulator ist nicht verbunden")
        if self.fail_next:
            self.fail_next = False
            self._connected = False
            raise DriverError("Simulierter Verbindungsabbruch")
        if self.latency_ms > 0:
            await asyncio.sleep(self.latency_ms / 1000.0 / self._time_scale)

    async def _run(self, coro):
        # Like the real controller: a command that was sent runs to its end,
        # even if the caller gives up waiting.
        async def locked():
            async with self._lock:
                return await coro
        return await asyncio.shield(asyncio.ensure_future(locked()))

    async def ping(self) -> None:
        await self._run(self._latency())

    async def configure(self, tool: Frame, wobj: Frame, speed: float, zone: str) -> None:
        async def do():
            await self._latency()
            self.model.set_tool(tool)
            self.model.set_wobj(wobj)
        await self._run(do())

    async def move_linear(self, pose: Pose, speed: float, zone: str) -> None:
        self._check(pose, speed)

        async def do():
            await self._latency()
            await self.model.move_linear(pose.xyz, pose.q, speed, zone_radius(zone))
        await self._run(do())

    async def move_joints(self, joints: Sequence[float], speed: float) -> None:
        async def do():
            await self._latency()
            await self.model.move_joints(joints, speed)
        await self._run(do())

    async def get_pose(self) -> Pose:
        async def do():
            await self._latency()
            xyz, quat = self.model.pose_in_wobj()
            return Pose(round(xyz[0], 2), round(xyz[1], 2), round(xyz[2], 2), quat)
        return await self._run(do())

    async def get_joints(self) -> list[float]:
        async def do():
            await self._latency()
            return self.model.get_joints()
        return await self._run(do())

    async def run_path(self, poses: Sequence[Pose], speed: float, zone: str,
                       on_progress: ProgressCallback | None = None) -> None:
        for pose in poses:
            self._check(pose, speed)

        async def do():
            await self._latency()
            radius = zone_radius(zone)
            for i, pose in enumerate(poses):
                last = i == len(poses) - 1
                # The last point of a buffered path is a stop point.
                await self.model.move_linear(pose.xyz, pose.q, speed, 0.0 if last else radius)
                if on_progress is not None:
                    on_progress(pose.xyz)
        await self._run(do())

    async def info(self) -> RobotInfo:
        await self._run(self._latency())
        return RobotInfo("SIM-0001", "Simulator", "IRB 120 (simuliert)")

    def actual_position(self) -> tuple[float, float, float] | None:
        return self.model.position_in_wobj_now()

    @property
    def has_actual_position(self) -> bool:
        return True

    def teleport_base(self, position) -> None:
        """Simulator only: put the TCP somewhere in base coordinates."""
        self.model.teleport_base(position)
