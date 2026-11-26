"""Virtual walls: the area the pen centre may be in, and sliding along it (CLAUDE.md §8.6)."""
from __future__ import annotations

import math

import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points

Point2 = tuple[float, float]

# A commanded straight step between two allowed points may cut a rounded wall
# corner by at most this much (chord of a 2–4 mm step on a ≥ 9 mm radius).
SEGMENT_SLACK = 0.25


def _polygons(geom) -> list[Polygon]:
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon) and not g.is_empty]


def min_channel_width(channel: Polygon, upper: float = 60.0, precision: float = 0.01) -> float:
    """Smallest corridor width: twice the erosion at which the topology changes."""

    def same_topology(r: float) -> bool:
        parts = _polygons(channel.buffer(-r))
        return len(parts) == 1 and len(parts[0].interiors) == len(channel.interiors)

    low, high = 0.0, upper
    if same_topology(high):
        return 2 * high
    while high - low > precision / 2:
        mid = (low + high) / 2
        if same_topology(mid):
            low = mid
        else:
            high = mid
    return round(2 * low, 2)


class Channel:
    """Allowed area for the pen centre = channel shrunk by pin radius + tolerance."""

    def __init__(self, channel: Polygon, pin_diameter: float, wall_tolerance: float,
                 anchor: Point2 | None = None):
        self.channel = channel
        self.pin_diameter = pin_diameter
        self.wall_tolerance = wall_tolerance
        self.inset = pin_diameter / 2.0 + wall_tolerance
        parts = _polygons(channel.buffer(-self.inset, join_style="round"))
        if not parts:
            raise ValueError("Mit diesem Stiftdurchmesser und dieser Toleranz bleibt keine "
                             "befahrbare Fläche übrig.")
        if anchor is not None:
            anchor_pt = Point(anchor)
            parts.sort(key=lambda p: (not p.covers(anchor_pt), p.distance(anchor_pt), -p.area))
        else:
            parts.sort(key=lambda p: -p.area)
        self.allowed: Polygon = parts[0]
        self.lost: list[Polygon] = parts[1:]          # cut off by narrow spots
        self._check = self.allowed.buffer(SEGMENT_SLACK)
        shapely.prepare(self.allowed)
        shapely.prepare(self._check)

    def wall_depth(self, p: Point2) -> float:
        """How deep the pen edge is in a wall (mm). Negative = still that much room."""
        pt = Point(p)
        distance = float(self.channel.boundary.distance(pt))
        inside = distance if self.channel.covers(pt) else -distance
        return self.pin_diameter / 2.0 - inside

    def bridged_walls(self) -> bool:
        """With a negative tolerance: are there walls thin enough to be driven through?"""
        grow = -self.inset
        if grow <= 0:
            return False
        # Walls thinner than 2 × grow vanish when they are opened by grow. Rounded inner
        # corners lose a little too (≤ 0.22 grow² each), so only bigger pieces count.
        minx, miny, maxx, maxy = self.channel.bounds
        margin = 3 * grow
        walls = shapely.box(minx - margin, miny - margin, maxx + margin, maxy + margin).difference(self.channel)
        opened = walls.buffer(-grow, join_style="round").buffer(grow, join_style="round")
        thin = walls.difference(opened)
        return any(part.area > 1.5 * grow * grow for part in _polygons(thin))

    @property
    def is_split(self) -> bool:
        return bool(self.lost)

    def contains(self, p: Point2) -> bool:
        return bool(self.allowed.covers(Point(p)))

    def snap(self, p: Point2) -> Point2:
        """Nearest allowed point (p itself if it is already allowed)."""
        pt = Point(p)
        if self.allowed.covers(pt):
            return (float(p[0]), float(p[1]))
        nearest = nearest_points(self.allowed, pt)[0]
        return self._inside((nearest.x, nearest.y))

    def _inside(self, p: Point2) -> Point2:
        """Pull a boundary point a hair inwards so that it is robustly `covers`-true."""
        if self.allowed.covers(Point(p)):
            return p
        c = self.allowed.representative_point()
        for eps in (1e-6, 1e-4, 1e-2):
            d = math.hypot(c.x - p[0], c.y - p[1]) or 1.0
            q = (p[0] + (c.x - p[0]) / d * eps, p[1] + (c.y - p[1]) / d * eps)
            if self.allowed.covers(Point(q)):
                return q
        return p

    def segment_ok(self, a: Point2, b: Point2) -> bool:
        if a == b:
            return self.contains(a)
        return bool(self._check.covers(LineString([a, b]))) and self.contains(b)

    def constrain(self, p_from: Point2, p_to: Point2) -> Point2:
        """Where a step from p_from towards p_to may actually go.

        1. The straight step if it stays inside.
        2. Otherwise slide: x-only, y-only and the allowed point nearest to the
           target are tried; the one with the most progress in the wanted
           direction wins.
        3. Otherwise stay.
        """
        p_from = (float(p_from[0]), float(p_from[1]))
        p_to = (float(p_to[0]), float(p_to[1]))
        dx, dy = p_to[0] - p_from[0], p_to[1] - p_from[1]
        step = math.hypot(dx, dy)
        if step < 1e-9:
            return p_from
        if self.segment_ok(p_from, p_to):
            return p_to
        ux, uy = dx / step, dy / step

        candidates: list[Point2] = []
        if abs(dx) > 1e-9 and abs(dy) > 1e-9:
            candidates += [(p_to[0], p_from[1]), (p_from[0], p_to[1])]
        nearest = nearest_points(self.allowed, Point(p_to))[0]
        candidates.append(self._inside((nearest.x, nearest.y)))
        # Shorter straight steps: reach a wall that is closer than one step.
        for factor in (0.5, 0.25):
            candidates.append((p_from[0] + dx * factor, p_from[1] + dy * factor))

        best, best_progress = p_from, 1e-6
        for cand in candidates:
            progress = (cand[0] - p_from[0]) * ux + (cand[1] - p_from[1]) * uy
            if progress <= best_progress:
                continue
            if math.hypot(cand[0] - p_from[0], cand[1] - p_from[1]) > step * 1.5:
                continue
            if self.segment_ok(p_from, cand):
                best, best_progress = cand, progress
        return best
