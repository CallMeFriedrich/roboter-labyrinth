"""SVG → channel polygon, islands, calibration holes and engraving (CLAUDE.md §5)."""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

from shapely.geometry import MultiPoint, Point, Polygon
from shapely.validation import make_valid
from svgelements import SVG, Arc, Close, CubicBezier, Group, Line, Move, Path, QuadraticBezier, Shape

CHORD_TOLERANCE = 0.05     # mm, well below the required 0.2 mm
HOLE_DIAMETER = 5.0
HOLE_OFFSET = 7.5          # hole centres sit 7.5 mm from each plate edge (any plate size)
MIN_PLATE, MAX_PLATE = 100.0, 600.0


def expected_holes(width: float, height: float) -> list[tuple[float, float]]:
    return [(HOLE_OFFSET, HOLE_OFFSET), (width - HOLE_OFFSET, HOLE_OFFSET),
            (HOLE_OFFSET, height - HOLE_OFFSET), (width - HOLE_OFFSET, height - HOLE_OFFSET)]


class SvgImportError(ValueError):
    """The SVG cannot be used as a labyrinth."""


@dataclass
class LabyrinthGeometry:
    width: float
    height: float
    channel: Polygon                                    # free area: exterior minus islands
    holes: list[tuple[float, float]]                    # centres of the calibration holes
    engraving: list[str] = field(default_factory=list)  # SVG path data (preview only)
    engraving_bounds: tuple[float, float, float, float] | None = None
    warnings: list[str] = field(default_factory=list)
    # Optional gate markers from the groups "Startlinie"/"Ziellinie": (centre, unit direction)
    # of a line or rectangle drawn across the corridor.
    markers: dict[str, tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=dict)
    marker_paths: list[str] = field(default_factory=list)  # SVG path data (preview only)
    logo: list[str] = field(default_factory=list)          # group "Gravur_…Logo…" for the visitor screen
    logo_bounds: tuple[float, float, float, float] | None = None

    @property
    def islands(self) -> list[Polygon]:
        return [Polygon(ring) for ring in self.channel.interiors]


def _flatten_curve(segment, out: list[tuple[float, float]]) -> None:
    """Adaptive subdivision of an arc/Bézier segment into chords."""

    def recurse(t0: float, p0, t1: float, p1, depth: int) -> None:
        tm = (t0 + t1) / 2.0
        pm = segment.point(tm)
        dx, dy = p1.x - p0.x, p1.y - p0.y
        length = math.hypot(dx, dy)
        if length < 1e-9:
            deviation = math.hypot(pm.x - p0.x, pm.y - p0.y)
        else:
            deviation = abs((pm.x - p0.x) * dy - (pm.y - p0.y) * dx) / length
        if depth < 12 and deviation > CHORD_TOLERANCE:
            recurse(t0, p0, tm, pm, depth + 1)
            recurse(tm, pm, t1, p1, depth + 1)
        else:
            out.append((p1.x, p1.y))

    pieces = 8  # fixed first split: full arcs and S-curves have a "flat" chord
    points = [segment.point(i / pieces) for i in range(pieces + 1)]
    for i in range(pieces):
        recurse(i / pieces, points[i], (i + 1) / pieces, points[i + 1], 0)


def _subpath_points(subpath) -> tuple[list[tuple[float, float]], bool]:
    points: list[tuple[float, float]] = []
    closed = False
    for segment in subpath:
        if isinstance(segment, Move):
            if segment.end is not None:
                points.append((segment.end.x, segment.end.y))
        elif isinstance(segment, Close):
            closed = True
        elif isinstance(segment, Line):
            points.append((segment.end.x, segment.end.y))
        elif isinstance(segment, (Arc, CubicBezier, QuadraticBezier)):
            _flatten_curve(segment, points)
    if len(points) > 2 and math.dist(points[0], points[-1]) < 1e-3:
        closed = True
        points.pop()
    cleaned: list[tuple[float, float]] = []
    for p in points:
        if not cleaned or math.dist(cleaned[-1], p) > 1e-6:
            cleaned.append(p)
    return cleaned, closed


def _walk(node, group_id: str, cut: list, engraving: list, markers: dict | None = None) -> None:
    if isinstance(node, Group):
        gid = node.id or group_id
        for child in node:
            _walk(child, gid, cut, engraving, markers)
    elif isinstance(node, Shape):
        if group_id == "Schnitt":
            cut.append(node)
        elif group_id.startswith("Gravur"):
            engraving.append(node)
            if "logo" in group_id.lower():
                node.values["_logo"] = True
        elif markers is not None and group_id.startswith("Startlinie"):
            markers.setdefault("start", []).append(node)
        elif markers is not None and group_id.startswith("Ziellinie"):
            markers.setdefault("finish", []).append(node)


def _marker_axis(shapes: list) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Centre and long direction of a line or (rotated) rectangle drawn across the corridor."""
    points: list[tuple[float, float]] = []
    for shape in shapes:
        for subpath in Path(shape).as_subpaths():
            pts, _ = _subpath_points(Path(subpath))
            points.extend(pts)
    if len(points) < 2:
        return None
    if len(points) == 2:
        (ax, ay), (bx, by) = points
    else:
        box = MultiPoint(points).minimum_rotated_rectangle
        if not isinstance(box, Polygon):
            coords = list(box.coords)
            (ax, ay), (bx, by) = coords[0], coords[-1]
        else:
            c = list(box.exterior.coords)[:4]
            # long axis through the middles of the two short edges
            if math.dist(c[0], c[1]) >= math.dist(c[1], c[2]):
                ax, ay = (c[1][0] + c[2][0]) / 2, (c[1][1] + c[2][1]) / 2
                bx, by = (c[3][0] + c[0][0]) / 2, (c[3][1] + c[0][1]) / 2
            else:
                ax, ay = (c[0][0] + c[1][0]) / 2, (c[0][1] + c[1][1]) / 2
                bx, by = (c[2][0] + c[3][0]) / 2, (c[2][1] + c[3][1]) / 2
    length = math.hypot(bx - ax, by - ay)
    if length < 1.0:
        return None
    return ((ax + bx) / 2, (ay + by) / 2), ((bx - ax) / length, (by - ay) / length)


def _is_hole(poly: Polygon) -> bool:
    minx, miny, maxx, maxy = poly.bounds
    w, h = maxx - minx, maxy - miny
    area = math.pi * (HOLE_DIAMETER / 2) ** 2
    return abs(w - HOLE_DIAMETER) < 0.6 and abs(h - HOLE_DIAMETER) < 0.6 and abs(poly.area - area) < 0.25 * area


def parse_svg(text: str) -> LabyrinthGeometry:
    try:
        # ppi=25.4 → one user unit of a "300mm"/viewBox 300 document is 1 mm.
        svg = SVG.parse(io.StringIO(text), ppi=25.4, reify=True)
    except Exception as exc:  # svgelements raises many different error types
        raise SvgImportError(f"Die Datei ist kein lesbares SVG ({exc}).") from exc

    warnings: list[str] = []
    viewbox = svg.viewbox
    if viewbox is None:
        raise SvgImportError("Das SVG hat keine viewBox. Erwartet wird z. B. "
                             "width=\"300mm\" height=\"300mm\" viewBox=\"0 0 300 300\".")
    width, height = float(viewbox.width), float(viewbox.height)
    if not (MIN_PLATE <= width <= MAX_PLATE and MIN_PLATE <= height <= MAX_PLATE):
        raise SvgImportError(f"Die Platte ist {width:g} × {height:g} mm groß. Erlaubt sind "
                             f"{MIN_PLATE:g} bis {MAX_PLATE:g} mm je Seite (1 SVG-Einheit = 1 mm).")
    if svg.width is not None and abs(float(svg.width) - width) > 0.5:
        warnings.append("Breite und viewBox passen nicht zusammen: 1 SVG-Einheit ist nicht 1 mm.")

    cut_shapes: list = []
    engraving_shapes: list = []
    marker_shapes: dict[str, list] = {}
    _walk(svg, "", cut_shapes, engraving_shapes, marker_shapes)
    if not cut_shapes:
        raise SvgImportError("Die Gruppe id=\"Schnitt\" fehlt oder ist leer.")

    polygons: list[Polygon] = []
    open_paths = 0
    for shape in cut_shapes:
        path = Path(shape)
        for subpath in path.as_subpaths():
            points, closed = _subpath_points(Path(subpath))
            if len(points) < 3:
                continue
            if not closed:
                open_paths += 1
                continue
            poly = Polygon(points)
            if not poly.is_valid:
                fixed = make_valid(poly)
                parts = [g for g in getattr(fixed, "geoms", [fixed]) if isinstance(g, Polygon)]
                if not parts:
                    continue
                poly = max(parts, key=lambda g: g.area)
            if poly.area > 1e-3:
                polygons.append(poly)
    if open_paths:
        warnings.append(f"{open_paths} offene Kontur(en) in der Gruppe „Schnitt“ wurden ignoriert.")

    holes: list[tuple[float, float]] = []
    contours: list[Polygon] = []
    plate_area = width * height
    for poly in polygons:
        if poly.area > 0.98 * plate_area:
            continue                      # plate outline
        if _is_hole(poly):
            c = poly.centroid
            holes.append((round(c.x, 3), round(c.y, 3)))
        else:
            contours.append(poly)
    if not contours:
        raise SvgImportError("Es wurde kein geschlossener Kanal gefunden.")

    contours.sort(key=lambda p: p.area, reverse=True)
    exterior = contours[0]
    islands: list[Polygon] = []
    ignored = 0
    for poly in contours[1:]:
        probe = poly.representative_point()
        depth = sum(1 for other in contours if other is not poly and other.contains(probe))
        if depth == 1 and exterior.contains(probe):
            islands.append(poly)
        else:
            ignored += 1
    if ignored:
        warnings.append(f"{ignored} weitere Kontur(en) außerhalb des Kanals wurden ignoriert.")

    channel = Polygon(exterior.exterior.coords, [i.exterior.coords for i in islands])
    if not channel.is_valid:
        fixed = make_valid(channel)
        parts = [g for g in getattr(fixed, "geoms", [fixed]) if isinstance(g, Polygon)]
        if not parts:
            raise SvgImportError("Die Kanalkontur ist ungültig (Selbstüberschneidung).")
        channel = max(parts, key=lambda g: g.area)
        warnings.append("Die Kanalkontur überschneidet sich selbst und wurde repariert.")

    holes = _sort_holes(holes)
    if len(holes) != 4:
        warnings.append(f"Es wurden {len(holes)} statt 4 Bohrungen (Ø 5 mm) gefunden. "
                        "Zum Einmessen müssen die Passpunkte dann von Hand stimmen.")
    else:
        for found, expected in zip(holes, expected_holes(width, height)):
            if math.dist(found, expected) > 0.5:
                warnings.append("Die Bohrungen liegen nicht auf den Sollpositionen "
                                "(7,5 mm vom Rand).")
                break

    engraving = [Path(shape).d() for shape in engraving_shapes]
    bounds = _bounds(engraving_shapes)
    logo_shapes = [s for s in engraving_shapes if s.values.get("_logo")] or engraving_shapes
    logo = [Path(shape).d() for shape in logo_shapes]
    logo_bounds = _bounds(logo_shapes)
    markers = {}
    for which, shapes in marker_shapes.items():
        axis = _marker_axis(shapes)
        if axis is None:
            name = "Startlinie" if which == "start" else "Ziellinie"
            warnings.append(f"Die Gruppe „{name}“ enthält keine brauchbare Linie.")
        else:
            markers[which] = axis
    marker_paths = [Path(shape).d() for shapes in marker_shapes.values() for shape in shapes]
    geometry = LabyrinthGeometry(width, height, channel, holes, engraving, bounds, warnings,
                                 markers, marker_paths)
    geometry.logo, geometry.logo_bounds = logo, logo_bounds
    return geometry


def _bounds(shapes) -> tuple[float, float, float, float] | None:
    bounds = None
    for shape in shapes:
        box = Path(shape).bbox()
        if box is None:
            continue
        bounds = box if bounds is None else (min(bounds[0], box[0]), min(bounds[1], box[1]),
                                             max(bounds[2], box[2]), max(bounds[3], box[3]))
    return bounds


def _sort_holes(holes: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Order: top left, top right, bottom left, bottom right."""
    if len(holes) != 4:
        return sorted(holes, key=lambda p: (p[1], p[0]))
    by_y = sorted(holes, key=lambda p: p[1])
    top, bottom = sorted(by_y[:2]), sorted(by_y[2:])
    return [top[0], top[1], bottom[0], bottom[1]]


def find_wide_spots(channel: Polygon, corridor_width: float) -> list[dict]:
    """Start/finish candidates: places clearly wider than the corridor (the circles).

    Returns dicts with centre and radius, sorted top to bottom, then left to right.
    """
    erosion = corridor_width / 2.0 + 1.0
    eroded = channel.buffer(-erosion)
    spots = []
    for part in getattr(eroded, "geoms", [eroded]):
        if part.is_empty or not isinstance(part, Polygon):
            continue
        c = part.centroid
        radius = math.sqrt(part.area / math.pi) + erosion
        # A start/finish circle is a dead end: exactly one corridor leaves it.
        # Junctions and bends are also "wide" but have two or more exits.
        centre = Point(c.x, c.y)
        band = centre.buffer(radius + 4.0).difference(centre.buffer(radius + 2.0)).intersection(channel)
        exits = [g for g in getattr(band, "geoms", [band]) if isinstance(g, Polygon) and g.area > 1.0]
        if len(exits) == 1:
            spots.append({"center": (c.x, c.y), "radius": radius})
    spots.sort(key=lambda s: (round(s["center"][1], 1), s["center"][0]))
    return spots


def point_in_channel(channel: Polygon, p: tuple[float, float]) -> bool:
    return channel.covers(Point(p))
