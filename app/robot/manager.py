"""Owns the driver: connection monitoring, frames, home and the basic moves.

Everything that makes the robot move goes through this class, so the safety
guard and the bookkeeping (last commanded position, at home or not) are in
one place.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Sequence

from shapely.geometry import Polygon

from ..db import Database
from ..geometry import frames
from ..geometry.frames import IDENTITY_FRAME, Frame
from ..settings import Config, SettingsStore
from .driver_base import DriverError, Pose, RobotDriver, RobotInfo, log
from .driver_extended import ExtendedDriver
from .driver_sim import SimDriver
from .driver_standard import StandardDriver
from .safety import Safety

Point3 = tuple[float, float, float]
DEFAULT_TOOL = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]


class RobotManager:
    def __init__(self, config: Config, settings: SettingsStore, db: Database,
                 on_connected: Callable[[], Awaitable[None]],
                 on_lost: Callable[[str], Awaitable[None]],
                 drivable: Callable[[], Polygon | None],
                 plate_size: Callable[[], tuple[float, float]]):
        self.config, self.settings, self.db = config, settings, db
        self.safety = Safety(config, settings)
        self._on_connected, self._on_lost = on_connected, on_lost
        self._drivable, self._plate_size = drivable, plate_size
        self.driver: RobotDriver = self._make_driver(settings["driver"])
        self.want_connected = True
        self.frame_mode = "plate"
        self.at_home = False
        self.home_confirmed = False
        self.commanded: Point3 | None = None      # last commanded position, current frame
        self._quat: tuple | None = None           # orientation kept while jogging in base
        self.info: RobotInfo | None = None
        self.last_error = ""
        self._last_command = 0.0
        self._last_attempt = 0.0
        self._monitor_task: asyncio.Task | None = None
        self._connecting = asyncio.Lock()

    # ----------------------------------------------------------------- driver
    def _make_driver(self, name: str) -> RobotDriver:
        if name == "sim":
            sim = self.config.sim
            return SimDriver(sim.acceleration, sim.latency_ms, sim.home_position, sim.time_scale)
        if name == "standard":
            r = self.config.robot
            return StandardDriver(r.ip, r.port, r.logger_port, r.connect_timeout_s, r.command_timeout_s)
        return ExtendedDriver()

    async def set_driver(self, name: str) -> None:
        await self.disconnect(keep_wanted=True)
        self.driver = self._make_driver(name)
        self.info = None
        self.last_error = ""
        self._last_attempt = 0.0

    @property
    def connected(self) -> bool:
        return self.driver.connected

    @property
    def acceleration(self) -> float:
        return self.config.sim.acceleration

    # ------------------------------------------------------------- frames/tool
    @property
    def tool(self) -> Frame:
        return Frame.from_list(self.db.get_setting("tool", DEFAULT_TOOL))

    @property
    def home_joints(self) -> list[float]:
        return self.db.get_setting("home_joints", self.config.robot.home_joints)

    def calibration(self) -> dict | None:
        """Active calibration; the simulator falls back to its own virtual plate."""
        stored = self.db.get_active_calibration()
        if stored is not None:
            return {"source": "measured", "created_at": stored["created_at"], "wobj": stored["wobj"],
                    "points": stored["points"], "pen_quat": stored.get("pen_quat")}
        if self.driver.name == "sim":
            sim = self.config.sim
            return {"source": "sim", "created_at": None, "wobj": [*sim.plate_origin, *sim.plate_quat],
                    "points": [None] * 4}
        return None

    @property
    def plate_frame(self) -> Frame | None:
        calibration = self.calibration()
        return Frame.from_list(calibration["wobj"]) if calibration else None

    def _guard(self):
        if self.frame_mode == "base":
            return self.safety.check_base
        return self.safety.plate_guard(self._plate_size(), self._drivable, lambda: self.commanded)

    async def apply_frame(self, mode: str | None = None) -> None:
        """(Re)send tool, work object, speed and zone; needed after every connect."""
        mode = mode or self.frame_mode
        if mode == "plate" and self.plate_frame is None:
            mode = "base"
        wobj = self.plate_frame if mode == "plate" else IDENTITY_FRAME
        await self._do(self.driver.configure(self.tool, wobj, self.settings["approach_speed"], "z1"))
        self.frame_mode = mode
        self.commanded = None
        self._quat = None
        self.driver.guard = self._guard()

    def measured_pen_quat(self) -> tuple | None:
        """Pen orientation (base frame) the plate was calibrated with, if it was recorded."""
        calibration = self.calibration()
        q = calibration.get("pen_quat") if calibration else None
        return tuple(q) if q else None

    def tool_quat(self) -> tuple:
        """Orientation of the pen in plate coordinates.

        After a measured calibration the robot keeps exactly the orientation the holes were
        measured with: the pen stays as it was taught (e.g. level), and any error in the tool
        offset cancels out, because calibration and driving use the same orientation.
        """
        pen = self.measured_pen_quat()
        plate = self.plate_frame
        if pen is not None and plate is not None:
            return plate.quat_to_local(pen)
        return frames.tool_orientation(self.settings["viewer_side"], self.settings["tool_roll_deg"])

    def viewer_side(self) -> str:
        """Side of the visitors. With a measured calibration it follows from where the robot stands."""
        plate = self.plate_frame
        if plate is not None and self.measured_pen_quat() is not None:
            robot_z = float(plate.to_local((0.0, 0.0, 0.0))[2])
            return "opposite" if robot_z > 0 else "robot"
        return self.settings["viewer_side"]

    def insert_z(self) -> float:
        return frames.insert_z(self.viewer_side(), self.settings["insert_depth"])

    def retract_z(self) -> float:
        return frames.retract_z(self.viewer_side(), self.settings["retract_distance"])

    # ------------------------------------------------------------- connection
    def start(self) -> None:
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor(), name="robot-monitor")

    async def stop(self) -> None:
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        await self.disconnect()

    async def connect(self) -> None:
        self.want_connected = True
        await self._try_connect()

    async def disconnect(self, keep_wanted: bool = False) -> None:
        if not keep_wanted:
            self.want_connected = False
        try:
            await self.driver.disconnect()
        except (DriverError, OSError):
            pass
        self._mark_unknown()

    def _mark_unknown(self) -> None:
        self.at_home = False
        self.home_confirmed = False
        self.commanded = None
        self._quat = None

    async def _try_connect(self) -> bool:
        async with self._connecting:
            if self.driver.connected:
                return True
            self._last_attempt = time.monotonic()
            try:
                await self.driver.connect()
                self._last_command = time.monotonic()
                self._mark_unknown()
                await self.apply_frame()
                self.info = await self.driver.info()
                self.last_error = ""
            except DriverError as exc:
                self.last_error = str(exc)
                try:
                    await self.driver.disconnect()
                except (DriverError, OSError):
                    pass
                return False
        log.info("Roboter verbunden (%s)", self.driver.name)
        await self._on_connected()
        return True

    async def _monitor(self) -> None:
        r = self.config.robot
        while True:
            await asyncio.sleep(0.5)
            try:
                if not self.want_connected:
                    continue
                now = time.monotonic()
                if not self.driver.connected:
                    if now - self._last_attempt >= r.reconnect_interval_s:
                        await self._try_connect()
                elif now - self._last_command >= r.ping_interval_s:
                    await self._do(self.driver.ping())
            except DriverError:
                pass                      # already handled in _do
            except Exception:             # the monitor must never die
                log.exception("Fehler in der Verbindungsüberwachung")

    async def _do(self, awaitable):
        """Await a driver call; on a connection problem mark everything unknown."""
        try:
            result = await awaitable
        except DriverError as exc:
            self.last_error = str(exc)
            self._mark_unknown()
            log.warning("Verbindung zum Roboter verloren: %s", exc)
            await self._on_lost(str(exc))
            raise
        self._last_command = time.monotonic()
        return result

    # ------------------------------------------------------------------ moves
    def _require_plate(self) -> None:
        if self.plate_frame is None:
            raise ValueError("Die Platte ist noch nicht eingemessen.")

    async def move_plate(self, x: float, y: float, z: float, speed: float, zone: str, kind: str) -> None:
        self.safety.check_speed(kind, speed)
        previous = self.commanded
        pose = Pose(x, y, z, self.tool_quat())
        self.driver._check(pose, speed)   # guard needs the *previous* position
        self.commanded = (x, y, z)        # set first: stays right if the caller is cancelled
        try:
            await self._do(self.driver.move_linear(pose, speed, zone))
        except ValueError:
            self.commanded = previous
            raise
        self.at_home = False

    async def run_plate_path(self, points: Sequence[tuple[float, float]], z: float, speed: float,
                             zone: str) -> None:
        if not points:
            return
        self.safety.check_speed("auto", speed)
        quat = self.tool_quat()
        poses = [Pose(x, y, z, quat) for x, y in points]

        def progress(xyz: Point3) -> None:
            self.commanded = xyz
        await self._do(self.driver.run_path(poses, speed, zone, progress))
        self.commanded = (points[-1][0], points[-1][1], z)
        self.at_home = False

    async def retract(self) -> None:
        """Pull the pen straight out of the plate (only if we know where it is)."""
        if self.frame_mode != "plate" or self.commanded is None:
            return
        x, y, z = self.commanded
        target = self.retract_z()
        if abs(z - target) > 0.01:
            await self.move_plate(x, y, target, self.settings["approach_speed"], "fine", "approach")

    async def go_home(self) -> None:
        await self.retract()
        await self._do(self.driver.move_joints(self.home_joints, self.config.robot.home_speed))
        self.commanded = None
        self._quat = None
        self.at_home = True
        self.home_confirmed = True

    async def go_to(self, xy: tuple[float, float]) -> None:
        """Home → above the point → insert the pen."""
        self._require_plate()
        if self.frame_mode != "plate":
            await self.apply_frame("plate")
        if not self.at_home:
            await self.go_home()
        speed = self.settings["approach_speed"]
        await self.move_plate(xy[0], xy[1], self.retract_z(), speed, "fine", "approach")
        await self.move_plate(xy[0], xy[1], self.insert_z(), speed, "fine", "approach")

    async def move_joints(self, joints: Sequence[float]) -> None:
        await self._do(self.driver.move_joints(joints, self.config.robot.home_speed))
        self.commanded = None
        self._quat = None
        self.at_home = False

    async def move_joints_at(self, joints: Sequence[float], speed: float) -> None:
        """Joint move with an explicit speed (idle show); the caller checked the path."""
        await self._do(self.driver.move_joints(joints, speed))
        self.commanded = None
        self._quat = None
        self.at_home = False

    async def read_pose(self) -> Pose:
        return await self._do(self.driver.get_pose())

    async def read_joints(self) -> list[float]:
        return await self._do(self.driver.get_joints())

    async def _prepare_admin(self, frame: str) -> None:
        """Switch to the frame and make sure position and orientation are known."""
        if frame not in ("base", "plate"):
            raise ValueError("Unbekanntes Koordinatensystem")
        if frame == "plate":
            self._require_plate()
        if self.frame_mode != frame:
            await self.apply_frame(frame)
        if self.commanded is None or (frame == "base" and self._quat is None):
            pose = await self.read_pose()
            self.commanded, self._quat = tuple(pose.xyz), pose.q

    async def jog(self, frame: str, delta: Point3, zone: str = "fine") -> None:
        """Manual move relative to the last commanded (or measured) position."""
        await self._prepare_admin(frame)
        x, y, z = (self.commanded[i] + delta[i] for i in range(3))
        await self._admin_move(frame, (x, y, z), zone)

    async def move_to(self, frame: str, target: Point3, zone: str = "fine") -> None:
        """Straight move to an absolute target; the head keeps its orientation (base frame)."""
        await self._prepare_admin(frame)
        await self._admin_move(frame, tuple(float(v) for v in target), zone)

    async def _admin_move(self, frame: str, target: Point3, zone: str) -> None:
        x, y, z = target
        speed = self.config.robot.admin_jog_speed
        if frame == "plate":
            await self.move_plate(x, y, z, speed, zone, "admin")
        else:
            previous = self.commanded
            self.driver._check(Pose(x, y, z, self._quat), speed)
            self.commanded = (x, y, z)
            try:
                await self._do(self.driver.move_linear(Pose(x, y, z, self._quat), speed, zone))
            except ValueError:
                self.commanded = previous
                raise
            self.at_home = False
        self.home_confirmed = False

    # ---------------------------------------------------------------- display
    def live_position(self) -> Point3 | None:
        actual = self.driver.actual_position() if self.driver.connected else None
        return actual if actual is not None else self.commanded
