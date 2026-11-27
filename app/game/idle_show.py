"""Idle show: when nobody plays for a while, the arm makes a few big, calm movements.

Safety first: every movement is a joint move (MoveAbsJ, joints interpolate linearly) and is
checked *before* anything is sent. Along each move the forward kinematics is sampled; the arm and
the pen must keep CLEARANCE mm away from

  * the plate and everything below it (stand) and behind it, as a box around the measured plate,
  * the table (z = TABLE_Z above the robot base),

stay inside the free circle around the robot that the admin set (radius) and not reach further
than REAR_X behind it, and every joint must stay 10° inside its range. Moves that fail are skipped.
Every pose must be able to reach the UPRIGHT pose safely, and the show always ends with
UPRIGHT → home, also when a visitor interrupts it.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..geometry.frames import Frame
from ..robot.kinematics import forward, within_limits

CLEARANCE = 80.0           # mm to the plate box
TABLE_Z = 60.0             # mm: lowest allowed height of any point (robot base = 0)
JOINT_MARGIN = 10.0        # degrees inside the axis ranges
SAMPLES = 24               # checks per move
MIN_SAFE_MOVES = 4
REAR_X = -200.0            # mm: no point further behind the robot
DEFAULT_RADIUS = 750.0     # mm: free circle around the robot's vertical axis (admin setting)

# Upper arm leaning back, pen up: the safe pose between all figures.
UPRIGHT = [0, -40, 30, 0, 60, 0]

# The choreography as absolute joint angles (degrees): stand up, look around, stretch up to the
# full height, stretch out to the left and right with the full span (turn first in the upright
# pose, so the arm never sweeps over the plate), nod, wave, turn the pen.
CHOREOGRAPHY: list[tuple[str, list[float]]] = [
    ("Aufrichten", UPRIGHT),
    ("Nach links schauen", [60, -40, 30, 0, 60, 0]),
    ("Nach rechts schauen", [-60, -40, 30, 0, 60, 0]),
    ("Aufrichten", UPRIGHT),
    ("Ganz nach oben strecken", [0, -5, -85, 0, 0, 180]),
    ("Aufrichten", UPRIGHT),
    ("Nach links drehen", [90, -40, 30, 0, 60, 0]),
    ("Links ganz ausstrecken", [90, 85, -85, 0, 0, 0]),
    ("Zurückziehen", [90, -40, 30, 0, 60, 0]),
    ("Nach rechts drehen", [-90, -40, 30, 0, 60, 0]),
    ("Rechts ganz ausstrecken", [-90, 85, -85, 0, 0, 0]),
    ("Zurückziehen", [-90, -40, 30, 0, 60, 0]),
    ("Aufrichten", UPRIGHT),
    ("Nicken", [0, -40, 50, 0, -15, 0]),
    ("Nicken", [0, -40, 20, 0, 75, 0]),
    ("Nicken", [0, -40, 50, 0, -15, 0]),
    ("Winken", [0, -40, 30, 50, 60, 0]),
    ("Winken", [0, -40, 30, -50, 60, 0]),
    ("Winken", [0, -40, 30, 50, 60, 0]),
    ("Stift drehen", [0, -40, 30, 0, 60, 150]),
    ("Stift drehen", [0, -40, 30, 0, 60, -150]),
    ("Aufrichten", UPRIGHT),
]


# The earlier, compact show: the arm stays close to the robot (fits in a circle of about 52 cm).
COMPACT: list[tuple[str, list[float]]] = [
    ("Aufrichten", UPRIGHT),
    ("Nach links schauen", [60, -40, 30, 0, 60, 0]),
    ("Nach rechts schauen", [-60, -40, 30, 0, 60, 0]),
    ("Aufrichten", UPRIGHT),
    ("Nicken", [0, -40, 50, 0, -15, 0]),
    ("Nicken", [0, -40, 20, 0, 75, 0]),
    ("Nicken", [0, -40, 50, 0, -15, 0]),
    ("Winken", [0, -40, 30, 50, 60, 0]),
    ("Winken", [0, -40, 30, -50, 60, 0]),
    ("Winken", [0, -40, 30, 50, 60, 0]),
    ("Stift drehen", [0, -40, 30, 0, 60, 150]),
    ("Stift drehen", [0, -40, 30, 0, 60, -150]),
    ("Aufrichten", UPRIGHT),
]

# Admin setting "idle_show_style": full = with the full span, compact = the earlier show.
STYLES = {"full": CHOREOGRAPHY, "compact": COMPACT}


@dataclass
class ShowMove:
    name: str
    joints: list[float]
    safe: bool
    reason: str = ""


class PlateBox:
    """Forbidden region around the plate (plate frame: x right, y down, z into the plate)."""

    def __init__(self, plate: Frame, width: float, height: float, clearance: float = CLEARANCE):
        self.plate, self.w, self.h, self.m = plate, width, height, clearance
        base_n = plate.to_local((0.0, 0.0, 0.0))[2]
        self.robot_side = 1.0 if base_n >= 0 else -1.0     # the robot stands on this side of the plate

    def violates(self, p) -> bool:
        u, v, n = self.plate.to_local(p)
        towards_robot = self.robot_side * n
        # In front of the plate (seen from the robot), beside it within the margin, or below it
        # (stand), or behind it: all forbidden closer than the clearance.
        return (-self.m <= u <= self.w + self.m) and (v >= -self.m) and (towards_robot < self.m)


def check_move(start, end, tool_xyz, box: PlateBox, radius: float = DEFAULT_RADIUS, limits=None) -> str:
    """'' if the joint move from start to end is safe, else the reason."""
    start, end = np.asarray(start, float), np.asarray(end, float)
    for i in range(SAMPLES + 1):
        q = start + (end - start) * (i / SAMPLES)
        if not within_limits(q, JOINT_MARGIN, limits):
            return "Achsgrenze"
        for p in forward(q, tool_xyz).checkpoints():
            if p[2] < TABLE_Z:
                return "zu nah am Tisch"
            if p[0] < REAR_X or float(np.hypot(p[0], p[1])) > radius:
                return "braucht mehr freien Umkreis"
            if box.violates(p):
                return "zu nah an der Platte"
    return ""


def scaled(joints, home, scale: float) -> list[float]:
    """A figure made smaller: scale 1 = full figure, 0.5 = half the swing, 0 = the upright pose.

    The controller's joint limits are not known exactly (only that they are tight). Scaling every
    figure around the upright pose keeps all axes close to it – and the upright pose leans back,
    away from the plate. (`home` is kept in the signature for the callers.)
    """
    return [round(u + scale * (v - u), 2) for v, u in zip(joints, UPRIGHT)]


def pivot(home, scale: float = 1.0) -> list[float]:
    """The pose between the figures: always the upright pose itself."""
    return list(UPRIGHT)


def plan(home: list[float], tool_xyz, plate: Frame, width: float, height: float,
         radius: float = DEFAULT_RADIUS, style: str = "full", limits=None,
         scale: float = 1.0) -> list[ShowMove]:
    """The choreography with every move checked from the previous *safe* pose."""
    box = PlateBox(plate, width, height)
    up = pivot(home, scale)

    def check_move(a, b, tool, bx, r):          # same checks, with the controller's joint limits
        return _check(a, b, tool, bx, r, limits)

    if (reason := check_move(home, home, tool_xyz, box, radius)):
        return [ShowMove("Home", list(home), False, f"Home selbst ist {reason}")]
    if (reason := check_move(home, up, tool_xyz, box, radius) or
            check_move(up, home, tool_xyz, box, radius)):
        return [ShowMove("Aufrichten", up, False, f"Weg zwischen Home und Aufrichten: {reason}")]
    moves: list[ShowMove] = []
    current = list(home)
    for name, figure in STYLES.get(style, CHOREOGRAPHY):
        joints = scaled(figure, home, scale)
        reason = check_move(current, joints, tool_xyz, box, radius)
        # Every pose must be able to get back to the upright pose (from there home is free).
        if not reason:
            reason = check_move(joints, up, tool_xyz, box, radius) and "Rückweg nicht frei"
        moves.append(ShowMove(name, list(joints), not reason, reason or ""))
        if not reason:
            current = list(joints)
    return moves


_check = check_move
