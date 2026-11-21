"""Start and finish gates: geometry, suggestion and crossing test (CLAUDE.md §5.4, §8.6)."""
from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polylabel

Point2 = tuple[float, float]


@dataclass(frozen=True)
class GateLine:
    """A line across the corridor. `n` is the unit normal in driving direction."""
    a: Point2
    b: Point2
    n: Point2

    @property
    def mid(self) -> Point2:
        return ((self.a[0] + self.b[0]) / 2, (self.a[1] + self.b[1]) / 2)

    def reversed(self) -> "GateLine":
        return GateLine(self.a, self.b, (-self.n[0], -self.n[1]))

    def to_dict(self) -> dict:
        return {"a": list(self.a), "b": list(self.b), "n": list(self.n)}

    @classmethod
    def from_dict(cls, data: dict) -> "GateLine":
        n = data["n"]
        length = math.hypot(n[0], n[1]) or 1.0
        return cls((float(data["a"][0]), float(data["a"][1])),
                   (float(data["b"][0]), float(data["b"][1])),
                   (n[0] / length, n[1] / length))


def crossing_fraction(line: GateLine, p0: Point2, p1: Point2) -> float | None:
    """Fraction t∈[0,1] along p0→p1 at which the gate is crossed *forwards*, else None."""
    rx, ry = p1[0] - p0[0], p1[1] - p0[1]
    if rx * line.n[0] + ry * line.n[1] <= 0:
        return None                                   # backwards or parallel
    sx, sy = line.b[0] - line.a[0], line.b[1] - line.a[1]
    denom = rx * sy - ry * sx
    if abs(denom) < 1e-12:
        return None
    qx, qy = line.a[0] - p0[0], line.a[1] - p0[1]
    t = (qx * sy - qy * sx) / denom
    u = (qx * ry - qy * rx) / denom
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return min(1.0, max(0.0, t))
    return None


def _cut(channel: Polygon, through: Point2, direction: Point2, reach: float = 80.0) -> tuple[Point2, Point2]:
    """Longest piece of the line through `through` that lies in the channel and is nearest to it."""
    probe = LineString([(through[0] - direction[0] * reach, through[1] - direction[1] * reach),
                        (through[0] + direction[0] * reach, through[1] + direction[1] * reach)])
    hit = probe.intersection(channel)
    pieces = [g for g in getattr(hit, "geoms", [hit]) if isinstance(g, LineString) and g.length > 1e-6]
    if not pieces:
        raise ValueError("Die Linie trifft den Kanal nicht.")
    target = Point(through)
    piece = min(pieces, key=lambda g: g.distance(target))
    (ax, ay), (bx, by) = piece.coords[0], piece.coords[-1]
    return (ax, ay), (bx, by)


def suggest_gate(channel: Polygon, center: Point2, radius: float, leaving: bool) -> GateLine:
    """Gate at the transition circle → corridor, perpendicular to the corridor."""
    c = Point(center)
    band = c.buffer(radius + 4.0).difference(c.buffer(radius + 2.0)).intersection(channel)
    parts = [g for g in getattr(band, "geoms", [band]) if isinstance(g, Polygon) and not g.is_empty]
    if not parts:
        raise ValueError("Am Kreis wurde kein Kanalausgang gefunden.")
    mouth = max(parts, key=lambda g: g.area).centroid
    ux, uy = mouth.x - center[0], mouth.y - center[1]
    d = math.hypot(ux, uy)
    ux, uy = ux / d, uy / d
    through = (center[0] + ux * (radius + 1.5), center[1] + uy * (radius + 1.5))
    a, b = _cut(channel, through, (-uy, ux))
    return GateLine(a, b, (ux, uy) if leaving else (-ux, -uy))


def gate_from_taps(channel: Polygon, p: Point2, q: Point2) -> GateLine:
    """Gate through two tapped points, snapped to the corridor walls.

    The normal direction is arbitrary here; use `orient` afterwards.
    """
    dx, dy = q[0] - p[0], q[1] - p[1]
    d = math.hypot(dx, dy)
    if d < 0.5:
        raise ValueError("Die zwei Punkte liegen zu nah beieinander.")
    t = (dx / d, dy / d)
    mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    a, b = _cut(channel, mid, t)
    return GateLine(a, b, (-t[1], t[0]))


def orient(line: GateLine, reference: Point2, away: bool) -> GateLine:
    """Make the normal point away from (start gate) or towards (finish gate) `reference`."""
    mx, my = line.mid
    dot = (mx - reference[0]) * line.n[0] + (my - reference[1]) * line.n[1]
    pointing_away = dot > 0
    return line if pointing_away == away else line.reversed()


def gate_from_marker(channel: Polygon, centre: Point2, direction: Point2,
                     is_start: bool) -> tuple[GateLine, Point2]:
    """Gate along a marker drawn across the corridor (group "Startlinie"/"Ziellinie").

    The line splits the channel; the smaller side is the start (or finish) area. Returns the
    oriented gate and a point deep inside that area, where the pen goes in (or comes out).
    """
    a, b = _cut(channel, centre, direction)
    cutter = LineString([a, b]).buffer(0.05, cap_style=2)
    rest = channel.difference(cutter)
    parts = [g for g in getattr(rest, "geoms", [rest]) if isinstance(g, Polygon) and g.area > 1.0]
    if len(parts) < 2:
        raise ValueError("Die Linie teilt den Kanal nicht – sie muss quer über den ganzen Gang gehen.")
    area = min(parts, key=lambda g: g.area)
    label = polylabel(area, tolerance=0.1)
    point = (float(label.x), float(label.y))
    gate = GateLine(a, b, (-direction[1], direction[0]))
    return orient(gate, point, away=is_start), point
