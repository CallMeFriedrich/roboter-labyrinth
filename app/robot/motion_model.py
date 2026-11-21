"""Kinematics-free model of the robot: a TCP that moves like SERVER.mod would move it.

Shared by the simulator driver and the fake controller, so both show the same
timing semantics:

* fine point  → the call returns after the TCP has stopped at the target,
* zone        → the call returns when the TCP enters the zone around the target
                and the TCP keeps its speed if the next command follows at once.
"""
from __future__ import annotations

import asyncio
import math
import time

import numpy as np

from ..geometry.frames import IDENTITY_FRAME, IDENTITY_QUAT, Frame

_REST_GAP = 0.06   # s without a new command after which the TCP has come to rest


class MotionModel:
    def __init__(self, acceleration: float = 1000.0,
                 home_position: tuple[float, float, float] = (374.0, 0.0, 420.0),
                 time_scale: float = 1.0):
        self.acceleration = acceleration
        self.time_scale = time_scale          # > 1 runs faster than real time (tests)
        self.home_position = np.asarray(home_position, dtype=float)
        self.tool: Frame = IDENTITY_FRAME
        self.wobj: Frame = IDENTITY_FRAME
        self.pos = self.home_position.copy()  # TCP in base coordinates
        self.quat_base = (0.70711, 0.0, 0.70711, 0.0)
        self.joints = [0.0, 45.0, 0.0, 0.0, -45.0, 0.0]
        self._joint_memory: dict[tuple, np.ndarray] = {}
        self._joints_valid = True
        self._v = 0.0
        self._pending_target: np.ndarray | None = None
        self._last_return = 0.0

    def _now(self) -> float:
        return time.monotonic() * self.time_scale

    # ------------------------------------------------------------------ frames
    def set_wobj(self, frame: Frame) -> None:
        self.wobj = frame

    def set_tool(self, frame: Frame) -> None:
        self.tool = frame

    def pose_in_wobj(self) -> tuple[list[float], tuple[float, float, float, float]]:
        self._settle()
        xyz = self.wobj.to_local(self.pos)
        return [float(v) for v in xyz], self.wobj.quat_to_local(self.quat_base)

    def position_in_wobj_now(self) -> tuple[float, float, float]:
        """Current position without settling – used for the live display."""
        xyz = self.wobj.to_local(self.pos)
        return (float(xyz[0]), float(xyz[1]), float(xyz[2]))

    def _settle(self) -> None:
        """Finish a zone move if no follow-up command arrived in time."""
        if self._pending_target is not None and self._now() - self._last_return > _REST_GAP:
            self.pos = self._pending_target.copy()
            self._pending_target = None
            self._v = 0.0

    # ----------------------------------------------------------------- motion
    async def move_linear(self, xyz, quat, speed: float, zone_radius: float) -> None:
        """Move the TCP to a target given in the current work object."""
        target = self.wobj.to_parent(xyz)
        self.quat_base = self.wobj.quat_to_parent(quat if quat is not None else IDENTITY_QUAT)
        await self._travel(target, max(speed, 0.1), zone_radius)
        self._joints_valid = False

    def _coast(self) -> None:
        """Between two zone moves the TCP keeps flying towards the previous target."""
        if self._pending_target is None:
            return
        gap = self._now() - self._last_return
        to_go = self._pending_target - self.pos
        distance = float(np.linalg.norm(to_go))
        travelled = self._v * max(gap, 0.0)
        if distance > 1e-9:
            self.pos = self._pending_target.copy() if travelled >= distance else self.pos + to_go / distance * travelled

    async def _travel(self, target: np.ndarray, speed: float, zone_radius: float) -> None:
        self._settle()
        self._coast()
        self._pending_target = None
        fine = zone_radius <= 0.0
        accel = self.acceleration
        last = self._now()
        while True:
            remaining = float(np.linalg.norm(target - self.pos))
            if fine and remaining <= 1e-9:
                self.pos, self._v = target.copy(), 0.0
                break
            if not fine and remaining <= zone_radius:
                self._pending_target = target.copy()
                break
            await asyncio.sleep(0.004)
            now = self._now()
            dt, last = min(now - last, 0.25), now
            # Integrate in 1 ms slices: independent of the coarse Windows timer.
            steps = max(1, int(dt / 0.001))
            h = dt / steps
            for _ in range(steps):
                remaining = float(np.linalg.norm(target - self.pos))
                limit = math.sqrt(2.0 * accel * remaining) if fine else speed
                self._v = min(self._v + accel * h, speed, max(limit, 1.0))
                step = self._v * h
                if step >= remaining:
                    self.pos = target.copy()
                    if fine:
                        self._v = 0.0
                    break
                self.pos = self.pos + (target - self.pos) / remaining * step
                if not fine and remaining - step <= zone_radius:
                    break
        self._last_return = self._now()

    def _joint_key(self, joints) -> tuple:
        return tuple(round(float(j), 1) for j in joints)

    async def move_joints(self, joints, speed: float) -> None:
        """All joint targets map to the home position unless they were read at another place."""
        self._settle()
        self._pending_target = None
        target = self._joint_memory.get(self._joint_key(joints), self.home_position)
        await self._travel(np.asarray(target, dtype=float), max(speed, 0.1) * 2.0, 0.0)
        self.joints = [float(j) for j in joints]
        self._joints_valid = True
        self.quat_base = (0.70711, 0.0, 0.70711, 0.0)

    def get_joints(self) -> list[float]:
        self._settle()
        if not self._joints_valid:
            # Pseudo joint values that identify this position (no kinematics).
            self.joints = [round(float(self.pos[1]) / 5.0, 2), round(float(self.pos[0]) / 10.0, 2),
                           round(float(self.pos[2]) / 10.0, 2), 0.0, -45.0, 0.0]
            self._joints_valid = True
        self._joint_memory[self._joint_key(self.joints)] = self.pos.copy()
        return list(self.joints)

    def teleport_base(self, position) -> None:
        self.pos = np.asarray(position, dtype=float).copy()
        self._pending_target = None
        self._v = 0.0
        self._joints_valid = False
