"""Standard driver: step jog over the unmodified SERVER.mod (CLAUDE.md §8.4)."""
from __future__ import annotations

import asyncio
import math
import time
from typing import Sequence

from ..geometry.frames import Frame
from .driver_base import DriverError, Pose, ProgressCallback, RobotDriver, RobotInfo, log
from .protocol import AbbClient, LoggerStream, ProtocolError

MAX_BUFFER = 512


class StandardDriver(RobotDriver):
    name = "standard"

    def __init__(self, ip: str, port: int = 5000, logger_port: int = 5001,
                 connect_timeout: float = 2.5, timeout: float = 5.0, use_logger: bool = True):
        super().__init__()
        self.client = AbbClient(ip, port, connect_timeout, timeout)
        self.logger = LoggerStream(ip, logger_port) if use_logger else None
        self._lock = asyncio.Lock()
        self._speed: float | None = None
        self._zone: str | None = None
        self._last_xyz: tuple[float, float, float] | None = None

    @property
    def connected(self) -> bool:
        return self.client.connected

    @property
    def last_traffic(self) -> float:
        return self.client.last_traffic

    async def _call(self, fn, *args, **kwargs):
        """Run one or more blocking protocol calls; never interleave two callers.

        Shielded: once a command is on the wire its answer must be read, even
        if the caller is cancelled. Otherwise the next command would read it.
        """
        async def locked():
            async with self._lock:
                try:
                    result = await asyncio.to_thread(fn, *args, **kwargs)
                except ProtocolError as exc:
                    raise DriverError(str(exc)) from exc
                self.latency_ms = self.client.last_latency * 1000.0
                return result
        return await asyncio.shield(asyncio.ensure_future(locked()))

    async def connect(self) -> None:
        await self._call(self.client.connect)
        self._speed = self._zone = self._last_xyz = None
        if self.logger is not None and not self.logger.running:
            started = await asyncio.to_thread(self.logger.start)
            log.info("LOGGER (Port %s) %s", self.logger.port, "verbunden" if started else "nicht erreichbar")

    async def disconnect(self) -> None:
        if self.logger is not None:
            self.logger.stop()
        async with self._lock:
            await asyncio.to_thread(self.client.close)

    async def ping(self) -> None:
        await self._call(self.client.ping)

    async def configure(self, tool: Frame, wobj: Frame, speed: float, zone: str) -> None:
        def do():
            self.client.set_tool(tool.origin, tool.quat)
            self.client.set_workobject(wobj.origin, wobj.quat)
            self.client.set_speed(speed)
            self.client.set_zone(zone)
        await self._call(do)
        self._speed, self._zone, self._last_xyz = speed, zone, None

    def _apply_motion_settings(self, speed: float, zone: str) -> None:
        """Blocking; only sends what changed (two extra round trips cost time in the jog loop)."""
        if self._speed is None or abs(self._speed - speed) > 1e-6:
            self.client.set_speed(speed)
            self._speed = speed
        if self._zone != zone:
            self.client.set_zone(zone)
            self._zone = zone

    def _move_timeout(self, target: tuple[float, float, float], speed: float) -> float:
        if self._last_xyz is None:
            return 60.0
        return math.dist(self._last_xyz, target) / max(speed, 1.0) + 2.0 + self.client.timeout

    async def move_linear(self, pose: Pose, speed: float, zone: str) -> None:
        self._check(pose, speed)

        def do():
            self._apply_motion_settings(speed, zone)
            self.client.move_cartesian(pose.xyz, pose.q, self._move_timeout(pose.xyz, speed))
        await self._call(do)
        self._last_xyz = pose.xyz

    async def move_joints(self, joints: Sequence[float], speed: float) -> None:
        def do():
            self._apply_motion_settings(speed, "fine")
            self.client.move_joints(joints, 60.0)
        await self._call(do)
        self._last_xyz = None

    async def get_pose(self) -> Pose:
        xyz, quat = await self._call(self.client.get_cartesian)
        return Pose(xyz[0], xyz[1], xyz[2], tuple(quat))

    async def get_joints(self) -> list[float]:
        return await self._call(self.client.get_joints)

    async def run_path(self, poses: Sequence[Pose], speed: float, zone: str,
                       on_progress: ProgressCallback | None = None) -> None:
        """Buffered path (codes 30–33): the controller flies through all points.

        The answer to code 33 only arrives after the last point, so there is no
        progress information in between unless LOGGER.mod is running.
        """
        if not poses:
            return
        if len(poses) > MAX_BUFFER:
            raise ValueError(f"Der Weg hat {len(poses)} Punkte, der Roboter-Puffer fasst {MAX_BUFFER}.")
        for pose in poses:
            self._check(pose, speed)
        length = 0.0
        previous = self._last_xyz
        for pose in poses:
            if previous is not None:
                length += math.dist(previous, pose.xyz)
            previous = pose.xyz

        def do():
            self._apply_motion_settings(speed, zone)   # buffer_add stores the current speed
            self.client.buffer_clear()
            for pose in poses:
                self.client.buffer_add(pose.xyz, pose.q)
            if self.client.buffer_len() != len(poses):
                self.client.buffer_clear()
                raise ProtocolError("Der Roboter-Puffer hat nicht alle Wegpunkte angenommen")
            started = time.monotonic()
            self.client.buffer_execute(length / max(speed, 1.0) + 10.0 + self.client.timeout)
            self.client.buffer_clear()
            return time.monotonic() - started
        await self._call(do)
        self._last_xyz = poses[-1].xyz
        if on_progress is not None:
            on_progress(poses[-1].xyz)

    async def info(self) -> RobotInfo:
        parts = await self._call(self.client.robot_info)
        parts = (parts + ["", "", ""])[:3]
        return RobotInfo(parts[0], parts[1], parts[2])

    def actual_position(self) -> tuple[float, float, float] | None:
        return self.logger.fresh_pose() if self.logger is not None else None

    @property
    def has_actual_position(self) -> bool:
        return self.logger is not None and self.logger.running
