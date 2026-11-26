"""Workspace and speed checks applied before every Cartesian move (CLAUDE.md §3).

These checks complement the physical safeguarding; they never replace the
emergency stop.
"""
from __future__ import annotations

from typing import Callable

from shapely.geometry import Point, Polygon

from ..geometry import frames
from ..settings import Config, SettingsStore
from .driver_base import Pose

SPEED_KINDS = {"visitor": "visitor_speed", "auto": "auto_speed", "approach": "approach_speed"}
# All three visitor modes share the visitor limit (the highest allowed of the three).
VISITOR_SPEED_KEYS = ("speed_slow", "visitor_speed", "speed_turbo")
_EPS = 0.05


class Safety:
    def __init__(self, config: Config, settings: SettingsStore):
        self._config = config
        self._settings = settings

    # ------------------------------------------------------------------ speed
    def speed_limit(self, kind: str) -> float:
        if kind == "admin":
            return self._config.robot.admin_jog_speed
        if kind == "visitor":
            return max(self._settings.limits(key)[1] for key in VISITOR_SPEED_KEYS)
        return self._settings.limits(SPEED_KINDS[kind])[1]

    def check_speed(self, kind: str, speed: float) -> float:
        limit = self.speed_limit(kind)
        if not (0 < speed <= limit + 1e-9):
            raise ValueError(f"Geschwindigkeit {speed:g} mm/s ist für „{kind}“ nicht erlaubt "
                             f"(Grenze {limit:g} mm/s)")
        return speed

    def absolute_speed_limit(self) -> float:
        return max(self.speed_limit(kind) for kind in ("visitor", "auto", "approach", "admin"))

    # ------------------------------------------------------------- base frame
    def check_base(self, pose: Pose, speed: float) -> None:
        box = self._config.workspace_base
        for name, value, (low, high) in (("x", pose.x, box.x), ("y", pose.y, box.y), ("z", pose.z, box.z)):
            if not (low - _EPS <= value <= high + _EPS):
                raise ValueError(f"Ziel außerhalb des Arbeitsraums: {name} = {value:.1f} mm "
                                 f"(erlaubt {low:g} … {high:g})")
        if speed > self.speed_limit("admin") + 1e-9:
            raise ValueError("Im Basis-Koordinatensystem ist nur die Einricht-Geschwindigkeit erlaubt")

    # ------------------------------------------------------------ plate frame
    def plate_guard(self, plate_size: tuple[float, float], drivable: Callable[[], Polygon | None],
                    current: Callable[[], tuple[float, float, float] | None]):
        """Build the guard for moves in plate coordinates.

        Allowed: inside the plate outline with z between retract and insert
        depth. With the pen past the plate surface the target must be inside
        the channel, and the pen may only move sideways while it stays inside.
        """
        def guard(pose: Pose, speed: float) -> None:
            side = self._settings["viewer_side"]
            z_low, z_high = frames.z_range(side, self._settings["insert_depth"],
                                           self._settings["retract_distance"])
            if not (-_EPS <= pose.x <= plate_size[0] + _EPS and -_EPS <= pose.y <= plate_size[1] + _EPS):
                raise ValueError("Ziel liegt außerhalb der Platte")
            if not (z_low - _EPS <= pose.z <= z_high + _EPS):
                raise ValueError(f"z = {pose.z:.1f} mm liegt nicht zwischen Rückzug und Eintauchtiefe")
            if speed > self.absolute_speed_limit() + 1e-9:
                raise ValueError(f"Geschwindigkeit {speed:g} mm/s über der harten Obergrenze")
            target_inserted = frames.is_inserted(side, pose.z)
            now = current()
            now_inserted = now is not None and frames.is_inserted(side, now[2])
            moves_sideways = now is not None and (abs(now[0] - pose.x) > 0.05 or abs(now[1] - pose.y) > 0.05)
            if target_inserted:
                area = drivable()
                if area is None or not area.covers(Point(pose.x, pose.y)):
                    raise ValueError("Eingetaucht darf der Stift nur im Kanal stehen")
            if now_inserted and moves_sideways and not target_inserted:
                raise ValueError("Erst gerade herausziehen, dann seitlich fahren")
        return guard
