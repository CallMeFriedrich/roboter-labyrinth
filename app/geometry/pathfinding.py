"""Shortest path through the allowed area: visibility graph + Dijkstra (CLAUDE.md §8.6)."""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import Point, Polygon
from shapely.geometry.polygon import orient as orient_polygon
from shapely.ops import nearest_points

from .lines import GateLine, crossing_fraction

Point2 = tuple[float, float]
_GUARD = 0.3         # keeps simplification and tolerance checks inside the allowed area


class PathError(ValueError):
    pass


@dataclass
class PathResult:
    points: list[Point2]
    length: float                 # whole polyline, mm
    start_index: int | None       # waypoint on the start gate
    finish_index: int | None      # waypoint on the finish gate
    timed_length: float           # between the two gates, mm

    def to_dict(self) -> dict:
        return {"points": [[round(x, 3), round(y, 3)] for x, y in self.points],
                "length": round(self.length, 2), "start_index": self.start_index,
                "finish_index": self.finish_index, "timed_length": round(self.timed_length, 2)}

    @classmethod
    def from_dict(cls, data: dict) -> "PathResult":
        return cls([(float(x), float(y)) for x, y in data["points"]], float(data["length"]),
                   data.get("start_index"), data.get("finish_index"), float(data.get("timed_length", 0)))


def _reflex_vertices(region: Polygon) -> list[Point2]:
    """Vertices where the free area bends around a wall (interior angle > 180°)."""
    region = orient_polygon(region, 1.0)     # exterior CCW, holes CW → free area on the left
    out: list[Point2] = []
    for ring in [region.exterior, *region.interiors]:
        pts = list(ring.coords)[:-1]
        n = len(pts)
        for i in range(n):
            ax, ay = pts[i - 1]
            bx, by = pts[i]
            cx, cy = pts[(i + 1) % n]
            cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
            if cross < -1e-9:
                out.append((bx, by))
    return out


def path_region(allowed: Polygon, margin: float, start: Point2) -> Polygon:
    shrunk = allowed.buffer(-(margin + _GUARD), quad_segs=3)
    parts = [g for g in getattr(shrunk, "geoms", [shrunk]) if isinstance(g, Polygon) and not g.is_empty]
    if not parts:
        raise PathError("Mit dieser Sicherheitsreserve bleibt keine Fläche für den Auto-Lauf.")
    start_pt = Point(start)
    part = min(parts, key=lambda g: g.distance(start_pt))
    simplified = part.simplify(0.25, preserve_topology=True)
    return simplified if isinstance(simplified, Polygon) and simplified.is_valid else part


def _snap(region: Polygon, p: Point2, limit: float = 12.0) -> Point2:
    pt = Point(p)
    if region.covers(pt):
        return p
    nearest = nearest_points(region, pt)[0]
    if nearest.distance(pt) > limit:
        raise PathError("Start oder Ziel liegt nicht im befahrbaren Bereich.")
    c = region.representative_point()
    d = math.hypot(c.x - nearest.x, c.y - nearest.y) or 1.0
    return (nearest.x + (c.x - nearest.x) / d * 1e-3, nearest.y + (c.y - nearest.y) / d * 1e-3)


def shortest_path(region: Polygon, start: Point2, goal: Point2) -> list[Point2]:
    start, goal = _snap(region, start), _snap(region, goal)
    nodes = np.array([start, goal, *_reflex_vertices(region)], dtype=float)
    check = region.buffer(0.04)
    shapely.prepare(check)

    n = len(nodes)
    dist = np.full(n, np.inf)
    prev = np.full(n, -1, dtype=int)
    done = np.zeros(n, dtype=bool)
    dist[0] = 0.0
    heap: list[tuple[float, int]] = [(0.0, 0)]
    while heap:
        d, i = heapq.heappop(heap)
        if done[i]:
            continue
        done[i] = True
        if i == 1:
            break
        others = np.flatnonzero(~done)
        if others.size == 0:
            break
        segs = np.empty((others.size, 2, 2))
        segs[:, 0, :] = nodes[i]
        segs[:, 1, :] = nodes[others]
        lengths = np.hypot(segs[:, 1, 0] - segs[:, 0, 0], segs[:, 1, 1] - segs[:, 0, 1])
        better = d + lengths < dist[others]        # only test edges that could help
        if not better.any():
            continue
        cand = others[better]
        visible = shapely.covers(check, shapely.linestrings(segs[better]))
        for j, length in zip(cand[visible], lengths[better][visible]):
            nd = d + float(length)
            if nd < dist[j]:
                dist[j] = nd
                prev[j] = i
                heapq.heappush(heap, (nd, int(j)))
    if not np.isfinite(dist[1]):
        raise PathError("Das Ziel ist vom Start aus nicht erreichbar.")
    path: list[Point2] = []
    k = 1
    while k != -1:
        path.append((float(nodes[k][0]), float(nodes[k][1])))
        k = int(prev[k])
    path.reverse()
    return path


def _insert_crossing(points: list[Point2], gate: GateLine, begin: int = 0) -> int | None:
    """Insert the forward crossing with `gate` as its own waypoint; return its index."""
    for i in range(begin, len(points) - 1):
        t = crossing_fraction(gate, points[i], points[i + 1])
        if t is None:
            continue
        if t < 1e-6:
            return i
        if t > 1 - 1e-6:
            return i + 1
        p0, p1 = points[i], points[i + 1]
        points.insert(i + 1, (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t))
        return i + 1
    return None


def polyline_length(points: list[Point2]) -> float:
    return sum(math.dist(points[i], points[i + 1]) for i in range(len(points) - 1))


def plan_path(allowed: Polygon, margin: float, start: Point2, goal: Point2,
              start_gate: GateLine | None, finish_gate: GateLine | None) -> PathResult:
    region = path_region(allowed, margin, start)
    points = shortest_path(region, start, goal)
    start_index = finish_index = None
    if start_gate is not None:
        start_index = _insert_crossing(points, start_gate)
        if start_index is None:
            raise PathError("Der Weg kreuzt die Startlinie nicht in Fahrtrichtung.")
    if finish_gate is not None:
        finish_index = _insert_crossing(points, finish_gate, start_index or 0)
        if finish_index is None:
            raise PathError("Der Weg kreuzt die Ziellinie nicht in Fahrtrichtung.")
    timed = 0.0
    if start_index is not None and finish_index is not None:
        timed = polyline_length(points[start_index:finish_index + 1])
    return PathResult(points, polyline_length(points), start_index, finish_index, timed)


def estimate_time(length: float, speed: float, acceleration: float = 1000.0) -> float:
    """Seconds for a rest-to-rest move with a trapezoidal speed profile."""
    if length <= 0 or speed <= 0:
        return 0.0
    ramp = speed * speed / acceleration
    if length < ramp:
        return 2.0 * math.sqrt(length / acceleration)
    return length / speed + speed / acceleration
