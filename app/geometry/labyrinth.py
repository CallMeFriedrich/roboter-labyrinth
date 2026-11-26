"""Everything the game needs to know about one labyrinth, built from a DB record."""
from __future__ import annotations

from typing import Any

from shapely.geometry import Polygon

from .channel import Channel, min_channel_width
from .lines import GateLine, gate_from_marker, suggest_gate
from .pathfinding import PathResult
from .svg_import import LabyrinthGeometry, find_wide_spots, parse_svg

Point2 = tuple[float, float]


def _ring(coords, digits: int = 2) -> list[list[float]]:
    return [[round(x, digits), round(y, digits)] for x, y in coords]


def _poly(poly: Polygon) -> dict:
    return {"outer": _ring(poly.exterior.coords), "holes": [_ring(r.coords) for r in poly.interiors]}


class LabyrinthRuntime:
    def __init__(self, record: dict, pin_diameter: float, wall_tolerance: float):
        self.id: int = record["id"]
        self.name: str = record["name"]
        self.geometry: LabyrinthGeometry = parse_svg(record["svg"])
        self.warnings: list[str] = list(self.geometry.warnings)
        self.min_width: float = min_channel_width(self.geometry.channel)
        self.spots = find_wide_spots(self.geometry.channel, self.min_width)

        self.start_point: Point2 | None = None
        self.finish_point: Point2 | None = None
        self.start_gate: GateLine | None = None
        self.finish_gate: GateLine | None = None
        self.gates_suggested = False
        self._load_gates(record)

        self.channel: Channel | None = None
        self.auto_channel: Channel | None = None    # the robot's own run never touches a wall
        try:
            self.channel = Channel(self.geometry.channel, pin_diameter, wall_tolerance, self.start_point)
            self.auto_channel = (self.channel if wall_tolerance >= 0 else
                                 Channel(self.geometry.channel, pin_diameter, 0.0, self.start_point))
        except ValueError as exc:
            self.warnings.append(str(exc))
        if self.channel is not None and self.channel.bridged_walls():
            self.warnings.append("Bei dieser Wandtoleranz liegen Gänge so nah beieinander, dass der Stift "
                                 "rechnerisch durch eine dünne Wand fahren könnte.")
        needed = pin_diameter + 2 * wall_tolerance
        if self.min_width < needed:
            self.warnings.append(
                f"Die schmalste Stelle ist {self.min_width:.1f} mm breit, nötig sind "
                f"{needed:.1f} mm (Stift + 2 × Toleranz).")
        if self.channel is not None and self.channel.is_split:
            self.warnings.append("Engstellen trennen den Kanal: Ein Teil ist nicht befahrbar "
                                 "(in der Vorschau rot).")
        if self.channel is not None and self.finish_point is not None \
                and not self.channel.contains(self.channel.snap(self.finish_point)):
            self.warnings.append("Das Ziel liegt nicht im befahrbaren Bereich.")

        self.path: PathResult | None = None
        if record.get("path"):
            try:
                self.path = PathResult.from_dict(record["path"])
            except (KeyError, TypeError, ValueError):
                self.path = None

    def _load_gates(self, record: dict) -> None:
        start, finish = record.get("start_line"), record.get("finish_line")
        if start and finish:
            self.start_gate, self.finish_gate = GateLine.from_dict(start), GateLine.from_dict(finish)
            self.start_point = tuple(start["point"])
            self.finish_point = tuple(finish["point"])
            return
        markers = self.geometry.markers
        if "start" in markers and "finish" in markers:
            try:
                self.start_gate, self.start_point = gate_from_marker(
                    self.geometry.channel, *markers["start"], is_start=True)
                self.finish_gate, self.finish_point = gate_from_marker(
                    self.geometry.channel, *markers["finish"], is_start=False)
                self.gates_suggested = True
                return
            except ValueError as exc:
                self.start_gate = self.finish_gate = self.start_point = self.finish_point = None
                self.warnings.append(f"Start-/Ziellinie aus der Zeichnung nicht nutzbar: {exc}")
        if len(self.spots) >= 2:
            first, last = self.spots[0], self.spots[-1]
            try:
                self.start_gate = suggest_gate(self.geometry.channel, first["center"], first["radius"], True)
                self.finish_gate = suggest_gate(self.geometry.channel, last["center"], last["radius"], False)
                self.start_point, self.finish_point = first["center"], last["center"]
                self.gates_suggested = True
            except ValueError as exc:
                self.warnings.append(f"Start-/Ziellinie konnte nicht vorgeschlagen werden: {exc}")
        else:
            self.warnings.append("Es wurden weder Start-/Ziellinien noch zwei Kreise für Start und "
                                 "Ziel gefunden. Bitte Start und Ziel von Hand setzen.")

    # ------------------------------------------------------------------ status
    @property
    def ready(self) -> bool:
        return (self.channel is not None and self.start_gate is not None
                and self.finish_gate is not None and self.path is not None
                and self.path.start_index is not None and self.path.finish_index is not None)

    def gate_records(self) -> tuple[dict | None, dict | None]:
        if not (self.start_gate and self.finish_gate and self.start_point and self.finish_point):
            return None, None
        return ({**self.start_gate.to_dict(), "point": list(self.start_point)},
                {**self.finish_gate.to_dict(), "point": list(self.finish_point)})

    def to_client(self) -> dict[str, Any]:
        g = self.geometry
        data: dict[str, Any] = {
            "id": self.id, "name": self.name, "width": g.width, "height": g.height,
            "channel": _poly(g.channel), "holes": [list(h) for h in g.holes],
            "engraving": g.engraving, "markers": g.marker_paths,
            "engraving_bounds": [float(v) for v in g.engraving_bounds] if g.engraving_bounds else None,
            "min_width": self.min_width, "island_count": len(g.channel.interiors),
            "spots": [{"center": list(s["center"]), "radius": s["radius"]} for s in self.spots],
            "warnings": self.warnings, "ready": self.ready,
            "allowed": _poly(self.channel.allowed) if self.channel else None,
            "lost": [_poly(p) for p in self.channel.lost] if self.channel else [],
            "start_point": list(self.start_point) if self.start_point else None,
            "finish_point": list(self.finish_point) if self.finish_point else None,
            "start_gate": self.start_gate.to_dict() if self.start_gate else None,
            "finish_gate": self.finish_gate.to_dict() if self.finish_gate else None,
            "path": self.path.to_dict() if self.path else None,
        }
        return data
