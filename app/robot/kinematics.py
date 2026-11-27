"""Forward kinematics of the ABB IRB 120 (positions of the arm, flange and pen tip).

Only used to *check* motions before they are sent (idle show): no inverse kinematics.
Geometry from the product manual (CLAUDE.md §2.1): shoulder 290 mm above the base, upper arm
270 mm, forearm offset 70 mm, forearm 302 mm, wrist centre to flange 72 mm. At all joints 0 the
wrist centre is at (302 | 0 | 630) and the flange points forward along +x (tool0 = [0.707, 0, 0.707, 0]).

Joint conventions (degrees, as on the FlexPendant): axis 2 positive tilts the upper arm forward,
axis 3 positive tilts the forearm down, axis 5 positive bends the flange down.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

D1, A2, A3, D4, D6 = 290.0, 270.0, 70.0, 302.0, 72.0

# Axis ranges (CLAUDE.md §2.1).
JOINT_LIMITS = [(-165, 165), (-110, 110), (-110, 70), (-160, 160), (-120, 120), (-400, 400)]


def _rx(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _ry(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rz(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


R_TOOL0_ZERO = _ry(math.pi / 2)          # flange orientation at all joints 0


@dataclass
class ArmPoints:
    shoulder: np.ndarray
    elbow: np.ndarray
    forearm: np.ndarray                  # end of the 70 mm offset
    wrist: np.ndarray
    flange: np.ndarray
    tcp: np.ndarray
    flange_rot: np.ndarray               # columns: flange x, y, z in base coordinates

    def checkpoints(self) -> list[np.ndarray]:
        """Points along the whole arm and the pen that must stay clear of obstacles."""
        pts = [self.elbow, (self.elbow + self.forearm) / 2, self.forearm,
               (self.forearm + self.wrist) / 2, self.wrist, self.flange]
        for f in (0.25, 0.5, 0.75, 1.0):              # along the pen holder and pen
            pts.append(self.flange + f * (self.tcp - self.flange))
        return pts


def forward(joints_deg, tool_xyz=(0.0, 0.0, 0.0)) -> ArmPoints:
    q = [math.radians(v) for v in joints_deg]
    r_base = _rz(q[0])
    t23 = q[1] + q[2]
    shoulder = np.array([0.0, 0.0, D1])
    elbow_p = shoulder + A2 * np.array([math.sin(q[1]), 0.0, math.cos(q[1])])
    forearm_p = elbow_p + A3 * np.array([math.sin(t23), 0.0, math.cos(t23)])
    wrist_p = forearm_p + D4 * np.array([math.cos(t23), 0.0, -math.sin(t23)])
    rot = r_base @ _ry(t23) @ _rx(q[3]) @ _ry(q[4]) @ _rx(q[5]) @ R_TOOL0_ZERO
    wrist = r_base @ wrist_p
    flange = wrist + D6 * rot[:, 2]
    tcp = flange + rot @ np.asarray(tool_xyz, dtype=float)
    return ArmPoints(r_base @ shoulder, r_base @ elbow_p, r_base @ forearm_p, wrist, flange, tcp, rot)


def within_limits(joints_deg, margin: float = 0.0, limits=None) -> bool:
    return all(lo + margin <= v <= hi - margin for v, (lo, hi) in zip(joints_deg, limits or JOINT_LIMITS))
