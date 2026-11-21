r"""Convert a labyrinth SVG (CLAUDE.md §5.1 convention) into a LightBurn project (.lbrn2).

Layers in the project:
    C00  Gravur      fill (scan)  – everything in groups "Gravur_*"
    C01  Plattenrand cut          – the board outline (switch off if the board is already cut to size)
    C02  Schnitt     cut          – channel, islands and the 4 calibration holes
    C03  Start/Ziel  line (light) – frames in the groups "Startlinie"/"Ziellinie", only marked

Curves are linearised with a chord error far below 0.01 mm. LightBurn's y axis points up,
so y is flipped (SVG 0 at the top → LightBurn <height> at the top); the part looks the same.

Power and speed in the file are only placeholders – set them in LightBurn for your wood and laser.

Usage:
    .venv\Scripts\python tools\svg_to_lightburn.py tests\data\Labyrinth_Deckplatte_Entwurf1.svg laser\Labyrinth_Entwurf1.lbrn2
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path as FsPath
from xml.sax.saxutils import escape

from svgelements import SVG, Arc, Close, CubicBezier, Group, Line, Move, Path, QuadraticBezier, Shape

SEGMENT_MM = 0.2            # max. length of one straight piece on a curve (sagitta < 0.002 mm at r = 2.5)
BOARD_TOL = 0.5             # a subpath this close to the full board is the board outline

LAYERS = {                  # index: (type, name, priority, min/max power %, speed mm/s)
    0: ("Scan", "Gravur", 0, 20, 30, 100),
    1: ("Cut", "Plattenrand", 2, 80, 100, 5),
    2: ("Cut", "Schnitt", 1, 80, 100, 5),
    3: ("Cut", "Start/Ziel-Rahmen", 0, 20, 30, 100),
}


def segment_points(seg) -> list[tuple[float, float]]:
    """Points after the segment start, up to and including its end."""
    if isinstance(seg, (Line, Close)):
        return [(seg.end.x, seg.end.y)]
    length = seg.length(error=1e-4)
    n = max(2, math.ceil(length / SEGMENT_MM))
    return [(p.x, p.y) for p in (seg.point(i / n) for i in range(1, n + 1))]


def subpaths(path: Path) -> list[list[tuple[float, float]]]:
    rings, ring = [], []
    for seg in path:
        if isinstance(seg, Move):
            if len(ring) > 2:
                rings.append(ring)
            ring = [(seg.end.x, seg.end.y)]
        elif isinstance(seg, (Line, Close, Arc, CubicBezier, QuadraticBezier)):
            if not ring and seg.start is not None:
                ring = [(seg.start.x, seg.start.y)]
            ring.extend(segment_points(seg))
    if len(ring) > 2:
        rings.append(ring)
    cleaned = []
    for ring in rings:
        pts = [ring[0]]
        for p in ring[1:]:
            if math.dist(p, pts[-1]) > 1e-6:
                pts.append(p)
        if math.dist(pts[0], pts[-1]) < 1e-6:
            pts.pop()                   # LineClosed closes the ring itself
        if len(pts) > 2:
            cleaned.append(pts)
    return cleaned


def is_board(ring, width, height) -> bool:
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return (abs(min(xs)) < BOARD_TOL and abs(min(ys)) < BOARD_TOL
            and abs(max(xs) - width) < BOARD_TOL and abs(max(ys) - height) < BOARD_TOL)


def num(v: float) -> str:
    text = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def shape_xml(index: int, ring, height: float) -> str:
    verts = "".join(f"V{num(x)} {num(height - y)}c0x1c1x1" for x, y in ring)
    return (f'    <Shape Type="Path" CutIndex="{index}">\n'
            f'        <XForm>1 0 0 1 0 0</XForm>\n'
            f'        <VertList>{verts}</VertList>\n'
            f'        <PrimList>LineClosed</PrimList>\n'
            f'    </Shape>\n')


def layer_xml(index: int) -> str:
    kind, name, priority, pmin, pmax, speed = LAYERS[index]
    return (f'    <CutSetting type="{kind}">\n'
            f'        <index Value="{index}"/>\n'
            f'        <name Value="{escape(name)}"/>\n'
            f'        <minPower Value="{pmin}"/>\n'
            f'        <maxPower Value="{pmax}"/>\n'
            f'        <speed Value="{speed}"/>\n'
            f'        <priority Value="{priority}"/>\n'
            f'    </CutSetting>\n')


def convert(svg_file: FsPath) -> tuple[str, dict[int, list]]:
    svg = SVG.parse(str(svg_file), ppi=25.4)          # 1 user unit = 1 mm (viewBox in mm)
    width, height = float(svg.viewbox.width), float(svg.viewbox.height)
    shapes: dict[int, list] = {0: [], 1: [], 2: [], 3: []}
    engraved, marked = set(), set()                     # shapes in "Gravur_*" / "Startlinie", "Ziellinie"
    for node in svg.elements():
        gid = (node.id or "") if isinstance(node, Group) else ""
        if gid.startswith("Gravur"):
            engraved.update(id(s) for s in node.select() if isinstance(s, Shape))
        elif gid.startswith(("Startlinie", "Ziellinie")):
            marked.update(id(s) for s in node.select() if isinstance(s, Shape))
    for element in svg.elements():
        if not isinstance(element, Shape):
            continue
        path = Path(element) if not isinstance(element, Path) else element
        path = abs(path)                                # apply transforms
        group = "engrave" if id(element) in engraved else "mark" if id(element) in marked else "cut"
        for ring in subpaths(path):
            if group == "mark":
                shapes[3].append(ring)
            elif group == "engrave":
                shapes[0].append(ring)
            elif is_board(ring, width, height):
                shapes[1].append(ring)
            else:
                shapes[2].append(ring)
    body = "".join(layer_xml(i) for i in LAYERS if shapes[i])
    body += "".join(shape_xml(i, ring, height) for i in (3, 0, 2, 1) for ring in shapes[i])
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<LightBurnProject AppVersion="1.7.00" FormatVersion="1" MaterialHeight="0" '
           'MirrorX="False" MirrorY="False">\n' + body + '</LightBurnProject>\n')
    return xml, shapes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("svg", type=FsPath)
    parser.add_argument("out", type=FsPath)
    args = parser.parse_args()
    xml, shapes = convert(args.svg)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(xml, encoding="utf-8")
    for index, rings in shapes.items():
        print(f"C{index:02d} {LAYERS[index][1]:<12} {len(rings):4d} Konturen, "
              f"{sum(len(r) for r in rings):6d} Punkte")
    print(f"Geschrieben: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
