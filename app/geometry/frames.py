"""Plate frame, calibration and quaternion helpers (CLAUDE.md §6).

Conventions
-----------
* Quaternions are ABB style ``[w, x, y, z]``.
* Plate coordinates: origin top left, x right, y down *as seen by the
  visitors*, z = ex × ey, which points away from the visitors into the plate.
* All signs that depend on which side the visitors stand on live in this
  module (`insert_z`, `retract_z`, `tool_orientation`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

HOLE_OFFSET = 7.5          # mm from each plate edge to the hole centres (any plate size)
PLATE_SIZE = 400.0         # default plate (Entwurf 1); the active labyrinth's viewBox wins
HOLE_SPACING = PLATE_SIZE - 2 * HOLE_OFFSET
DISTANCE_TOLERANCE = 2.0   # mm, plausibility of measured hole distances
CHECK_TOLERANCE = 2.0      # mm, deviation at the 4th hole


def holes_plate(width: float = PLATE_SIZE, height: float = PLATE_SIZE) -> dict[int, tuple[float, float]]:
    """Plate coordinates of the four holes, order of the wizard (always 7.5 mm from the edges)."""
    return {1: (HOLE_OFFSET, HOLE_OFFSET), 2: (width - HOLE_OFFSET, HOLE_OFFSET),
            3: (HOLE_OFFSET, height - HOLE_OFFSET), 4: (width - HOLE_OFFSET, height - HOLE_OFFSET)}


HOLES_PLATE = holes_plate()

Quat = tuple[float, float, float, float]
IDENTITY_QUAT: Quat = (1.0, 0.0, 0.0, 0.0)


# ------------------------------------------------------------------ quaternions
def quat_normalize(q) -> Quat:
    arr = np.asarray(q, dtype=float)
    norm = float(np.linalg.norm(arr))
    if norm < 1e-12:
        raise ValueError("Quaternion mit Länge 0")
    arr = arr / norm
    return (float(arr[0]), float(arr[1]), float(arr[2]), float(arr[3]))


def quat_mul(a, b) -> Quat:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw)


def quat_conj(q) -> Quat:
    return (q[0], -q[1], -q[2], -q[3])


def quat_to_rotmat(q) -> np.ndarray:
    w, x, y, z = quat_normalize(q)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def rotmat_to_quat(rot: np.ndarray) -> Quat:
    """Shepperd's method: numerically robust for every rotation."""
    m = np.asarray(rot, dtype=float)
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    candidates = [trace, m[0, 0], m[1, 1], m[2, 2]]
    k = int(np.argmax(candidates))
    if k == 0:
        w = 0.5 * math.sqrt(1.0 + trace)
        f = 0.25 / w
        q = (w, (m[2, 1] - m[1, 2]) * f, (m[0, 2] - m[2, 0]) * f, (m[1, 0] - m[0, 1]) * f)
    elif k == 1:
        x = 0.5 * math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
        f = 0.25 / x
        q = ((m[2, 1] - m[1, 2]) * f, x, (m[0, 1] + m[1, 0]) * f, (m[0, 2] + m[2, 0]) * f)
    elif k == 2:
        y = 0.5 * math.sqrt(1.0 - m[0, 0] + m[1, 1] - m[2, 2])
        f = 0.25 / y
        q = ((m[0, 2] - m[2, 0]) * f, (m[0, 1] + m[1, 0]) * f, y, (m[1, 2] + m[2, 1]) * f)
    else:
        z = 0.5 * math.sqrt(1.0 - m[0, 0] - m[1, 1] + m[2, 2])
        f = 0.25 / z
        q = ((m[1, 0] - m[0, 1]) * f, (m[0, 2] + m[2, 0]) * f, (m[1, 2] + m[2, 1]) * f, z)
    q = quat_normalize(q)
    return q if q[0] >= 0 else (-q[0], -q[1], -q[2], -q[3])


def quat_about_z(angle_deg: float) -> Quat:
    half = math.radians(angle_deg) / 2.0
    return (math.cos(half), 0.0, 0.0, math.sin(half))


# ------------------------------------------------------------------------ frame
@dataclass(frozen=True)
class Frame:
    """Rigid transform: p_parent = origin + R(quat) · p_local."""
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)
    quat: Quat = IDENTITY_QUAT

    @property
    def rot(self) -> np.ndarray:
        return quat_to_rotmat(self.quat)

    def to_parent(self, p) -> np.ndarray:
        return np.asarray(self.origin, dtype=float) + self.rot @ np.asarray(p, dtype=float)

    def to_local(self, p) -> np.ndarray:
        return self.rot.T @ (np.asarray(p, dtype=float) - np.asarray(self.origin, dtype=float))

    def quat_to_parent(self, q) -> Quat:
        return quat_normalize(quat_mul(self.quat, q))

    def quat_to_local(self, q) -> Quat:
        return quat_normalize(quat_mul(quat_conj(self.quat), q))

    def as_list(self) -> list[float]:
        return [*map(float, self.origin), *map(float, self.quat)]

    @classmethod
    def from_list(cls, values) -> "Frame":
        if values is None or len(values) != 7:
            raise ValueError("Frame braucht 7 Werte: x y z q1 q2 q3 q4")
        return cls(tuple(float(v) for v in values[:3]), quat_normalize(values[3:]))


IDENTITY_FRAME = Frame()


# ------------------------------------------------------------------ calibration
@dataclass
class CalibrationResult:
    frame: Frame
    distance_12: float
    distance_13: float
    skew_deg: float                      # deviation of the measured corner from 90°
    check_error: float | None = None     # mm at the 4th hole, None if not measured
    warnings: list[str] = field(default_factory=list)
    expected_12: float = HOLE_SPACING    # nominal hole distances for this plate
    expected_13: float = HOLE_SPACING

    @property
    def ok(self) -> bool:
        return not self.warnings


def calibrate(p1, p2, p3, p4=None, width: float = PLATE_SIZE, height: float = PLATE_SIZE) -> CalibrationResult:
    """3-point calibration from the hole centres (base coordinates, mm).

    p1 = top left, p2 = top right, p3 = bottom left, p4 = bottom right (check),
    always as seen by the visitors. `width`/`height` = plate size in mm.
    """
    p1, p2, p3 = (np.asarray(p, dtype=float) for p in (p1, p2, p3))
    d12 = float(np.linalg.norm(p2 - p1))
    d13 = float(np.linalg.norm(p3 - p1))
    if d12 < 1e-6 or d13 < 1e-6:
        raise ValueError("Die Messpunkte liegen aufeinander.")
    ex = (p2 - p1) / d12
    v = p3 - p1
    ey_raw = v - np.dot(v, ex) * ex
    if np.linalg.norm(ey_raw) < 1e-6:
        raise ValueError("Die drei Messpunkte liegen auf einer Geraden.")
    ey = ey_raw / np.linalg.norm(ey_raw)
    ez = np.cross(ex, ey)
    origin = p1 - HOLE_OFFSET * ex - HOLE_OFFSET * ey
    quat = rotmat_to_quat(np.column_stack([ex, ey, ez]))
    frame = Frame(tuple(float(c) for c in origin), quat)

    skew = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(ex, v / d13)))))) - 90.0
    result = CalibrationResult(frame, d12, d13, skew)
    result.expected_12 = width - 2 * HOLE_OFFSET
    result.expected_13 = height - 2 * HOLE_OFFSET
    if abs(d12 - result.expected_12) > DISTANCE_TOLERANCE:
        result.warnings.append(
            f"Abstand oben links → oben rechts ist {d12:.2f} mm statt {result.expected_12:g} mm.")
    if abs(d13 - result.expected_13) > DISTANCE_TOLERANCE:
        result.warnings.append(
            f"Abstand oben links → unten links ist {d13:.2f} mm statt {result.expected_13:g} mm.")
    if p4 is not None:
        hole4 = holes_plate(width, height)[4]
        expected = frame.to_parent((hole4[0], hole4[1], 0.0))
        result.check_error = float(np.linalg.norm(np.asarray(p4, dtype=float) - expected))
        if result.check_error > CHECK_TOLERANCE:
            result.warnings.append(
                f"Kontrollbohrung unten rechts weicht um {result.check_error:.2f} mm ab.")
    return result


# ------------------------------------------------------- side dependent signs
def _check_side(viewer_side: str) -> None:
    if viewer_side not in ("robot", "opposite"):
        raise ValueError(f"viewer_side muss 'robot' oder 'opposite' sein, nicht {viewer_side!r}")


def insert_z(viewer_side: str, insert_depth: float) -> float:
    """Plate z of the pen tip while it is inside the channel.

    ez points away from the visitors. With the visitors opposite the robot the
    robot stands on the +ez side, so pushing the pen into the plate is −z.
    """
    _check_side(viewer_side)
    return -abs(insert_depth) if viewer_side == "opposite" else abs(insert_depth)


def retract_z(viewer_side: str, retract_distance: float) -> float:
    """Plate z of the pen tip when it is pulled back out of the plate."""
    _check_side(viewer_side)
    return abs(retract_distance) if viewer_side == "opposite" else -abs(retract_distance)


def z_range(viewer_side: str, insert_depth: float, retract_distance: float) -> tuple[float, float]:
    a, b = insert_z(viewer_side, insert_depth), retract_z(viewer_side, retract_distance)
    return (min(a, b), max(a, b))


def is_inserted(viewer_side: str, z: float, margin: float = 0.5) -> bool:
    """True if the pen tip is past the plate surface (inside the wood plane)."""
    _check_side(viewer_side)
    return z < margin if viewer_side == "opposite" else z > -margin


def tool_orientation(viewer_side: str, roll_deg: float = 0.0) -> Quat:
    """Tool orientation in plate coordinates: pen perpendicular, pointing at the plate.

    opposite: tool z = −ez → 180° about x, i.e. [0, 1, 0, 0].
    robot:    tool z = +ez → identity.
    `roll_deg` turns the tool about the pen axis.
    """
    _check_side(viewer_side)
    base: Quat = (0.0, 1.0, 0.0, 0.0) if viewer_side == "opposite" else IDENTITY_QUAT
    return quat_normalize(quat_mul(base, quat_about_z(roll_deg)))


def tool_axis_in_plate(viewer_side: str, roll_deg: float = 0.0) -> np.ndarray:
    """Direction of the tool z axis in plate coordinates (for tests/diagnostics)."""
    return quat_to_rotmat(tool_orientation(viewer_side, roll_deg)) @ np.array([0.0, 0.0, 1.0])
