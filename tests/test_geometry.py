"""Geometry: SVG import, allowed area, sliding, gates, shortest path (CLAUDE.md §12, M2)."""
from __future__ import annotations

import math

import pytest
from shapely.geometry import LineString, Point

from app.geometry.channel import SEGMENT_SLACK, Channel, min_channel_width
from app.geometry.labyrinth import LabyrinthRuntime
from app.geometry.lines import GateLine, crossing_fraction, gate_from_taps, orient, suggest_gate
from app.geometry.pathfinding import PathError, estimate_time, plan_path
from app.geometry.svg_import import SvgImportError, find_wide_spots, parse_svg

from .conftest import make_simple_svg

TOP_RIGHT = (368.18, 31.82)
BOTTOM_LEFT = (31.82, 368.18)


# ---------------------------------------------------------------- SVG import
def test_draft_is_recognised(draft):
    assert draft.warnings == []
    assert (draft.width, draft.height) == (400, 400)
    assert draft.holes == [(7.5, 7.5), (392.5, 7.5), (7.5, 392.5), (392.5, 392.5)]
    assert len(draft.islands) == 2
    assert draft.channel.is_valid
    assert draft.channel.bounds == pytest.approx((18.818, 18.818, 381.182, 381.182), abs=0.01)
    boxes = sorted(tuple(round(v, 1) for v in island.bounds) for island in draft.islands)
    assert boxes == [(73.5, 39.8, 192.0, 124.7), (241.6, 208.0, 360.2, 292.9)]


def test_draft_engraving_is_preview_only(draft):
    assert len(draft.engraving) >= 1
    x0, y0, x1, y1 = draft.engraving_bounds
    assert 250 < x0 < 260 and 325 < y0 < 335 and 370 < x1 < 380 and 368 < y1 < 376
    # The logo sits in solid wood: it must not have become part of the channel.
    assert not draft.channel.intersects(Point((x0 + x1) / 2, (y0 + y1) / 2))


def test_draft_channel_width_is_16_mm(draft):
    assert min_channel_width(draft.channel) == pytest.approx(16.0, abs=0.1)


def test_draft_circles_are_found(draft):
    spots = find_wide_spots(draft.channel, 16.0)
    assert len(spots) == 2
    assert spots[0]["center"] == pytest.approx(TOP_RIGHT, abs=0.5)
    assert spots[1]["center"] == pytest.approx(BOTTOM_LEFT, abs=0.5)
    assert spots[0]["radius"] == pytest.approx(13.0, abs=0.5)


def test_curves_are_linearised_finely(simple_svg):
    geometry = parse_svg(simple_svg)
    # Each hole is two half arcs; its polygon must be very close to a Ø 5 mm circle.
    hole = Point(7.5, 7.5).buffer(2.5, quad_segs=64)
    assert geometry.holes[0] == pytest.approx((7.5, 7.5), abs=0.01)
    assert geometry.channel.area == pytest.approx(
        2 * math.pi * 13 ** 2 + 140 * 16 - 2 * _circle_segment_overlap(), rel=0.01)
    assert hole.area == pytest.approx(math.pi * 2.5 ** 2, rel=0.001)


def _circle_segment_overlap() -> float:
    # Part of the 16 mm corridor that lies inside one Ø 26 circle (half circle side).
    r, h = 13.0, 8.0
    x = math.sqrt(r * r - h * h)
    return 2 * (0.5 * x * h + 0.5 * r * r * math.asin(h / r))


def test_missing_holes_and_bad_files_are_reported():
    geometry = parse_svg(make_simple_svg(holes=2))
    assert any("Bohrungen" in w for w in geometry.warnings)
    with pytest.raises(SvgImportError):
        parse_svg("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 400 400'><g id='Other'/></svg>")
    with pytest.raises(SvgImportError):
        parse_svg("this is not an svg")


# -------------------------------------------------------------- allowed area
@pytest.fixture(scope="module")
def draft_channel(draft):
    return Channel(draft.channel, pin_diameter=8, wall_tolerance=1.0, anchor=TOP_RIGHT)


def test_allowed_area_is_the_shrunk_channel(draft, draft_channel):
    assert not draft_channel.is_split
    assert draft_channel.inset == 5.0
    assert draft_channel.contains(TOP_RIGHT)
    # Centre line of the corridor is allowed, a point 4 mm from the wall is not.
    assert draft_channel.contains((340.0, 31.82))
    assert not draft_channel.contains((340.0, 31.82 + 4.5))
    assert draft.channel.buffer(-4.99).covers(draft_channel.allowed)


def test_negative_tolerance_lets_the_pen_touch_the_wall(draft):
    touching = Channel(draft.channel, pin_diameter=8, wall_tolerance=-1.0, anchor=TOP_RIGHT)
    assert touching.contains((340.0, 31.82 + 4.5))


def test_too_thick_pen_splits_or_empties_the_channel(draft):
    channel = Channel(draft.channel, pin_diameter=14, wall_tolerance=3.0, anchor=TOP_RIGHT)
    assert channel.is_split                       # only the two circles survive
    assert channel.contains(TOP_RIGHT)
    with pytest.raises(ValueError):
        Channel(draft.channel, pin_diameter=14, wall_tolerance=10.0)


def test_constrain_free_move_and_zero_move(draft_channel):
    start = (340.0, 31.82)
    assert draft_channel.constrain(start, (338.0, 31.82)) == (338.0, 31.82)
    assert draft_channel.constrain(start, start) == start


def test_constrain_stops_at_a_wall(draft_channel):
    p = (340.0, 31.82)
    for _ in range(10):                            # push straight up into the wall
        p = draft_channel.constrain(p, (p[0], p[1] - 2.0))
        assert draft_channel.contains(p)
    assert p[0] == pytest.approx(340.0, abs=0.01)
    assert p[1] == pytest.approx(31.82 - 3.0, abs=0.05)     # 8 mm half width − 5 mm inset
    assert draft_channel.constrain(p, (p[0], p[1] - 2.0)) == p


def test_constrain_slides_along_a_wall(draft_channel):
    p = (345.0, 31.82)
    for _ in range(6):                             # diagonal: up-left against the upper wall
        p = draft_channel.constrain(p, (p[0] - 1.5, p[1] - 1.5))
    assert p[1] == pytest.approx(31.82 - 3.0, abs=0.05)
    before = p[0]
    for _ in range(5):
        p = draft_channel.constrain(p, (p[0] - 1.5, p[1] - 1.5))
        assert draft_channel.contains(p)
    assert p[0] == pytest.approx(before - 7.5, abs=0.05)     # full sideways progress


def test_constrain_slides_around_the_circle_and_never_leaves(draft_channel):
    # Push into the rounded wall of the start circle from many directions.
    for angle in range(0, 360, 15):
        d = (math.cos(math.radians(angle)), math.sin(math.radians(angle)))
        p = TOP_RIGHT
        for _ in range(40):
            nxt = draft_channel.constrain(p, (p[0] + d[0] * 2.0, p[1] + d[1] * 2.0))
            assert draft_channel.contains(nxt)
            assert draft_channel.allowed.buffer(SEGMENT_SLACK + 1e-6).covers(LineString([p, nxt])) or p == nxt
            p = nxt


def test_no_tunnelling_through_walls(draft_channel):
    # A huge step must not jump into the neighbouring corridor.
    p = (340.0, 31.82)
    q = draft_channel.constrain(p, (340.0, 31.82 + 33.6))
    assert abs(q[1] - 31.82) <= 3.05


# --------------------------------------------------------------------- gates
def test_crossing_forwards_backwards_and_missing():
    gate = GateLine((10, 0), (10, 10), (1, 0))
    assert crossing_fraction(gate, (8, 5), (12, 5)) == pytest.approx(0.5)
    assert crossing_fraction(gate, (9, 5), (13, 5)) == pytest.approx(0.25)
    assert crossing_fraction(gate, (12, 5), (8, 5)) is None          # backwards
    assert crossing_fraction(gate, (8, 5), (9.5, 5)) is None         # not reached
    assert crossing_fraction(gate, (8, 20), (12, 20)) is None        # passes beside the gate
    assert crossing_fraction(gate, (10, 2), (10, 8)) is None         # along the gate
    assert crossing_fraction(gate.reversed(), (12, 5), (8, 5)) == pytest.approx(0.5)


def test_suggested_gates_of_the_draft(draft):
    spots = find_wide_spots(draft.channel, 16.0)
    start = suggest_gate(draft.channel, spots[0]["center"], spots[0]["radius"], leaving=True)
    finish = suggest_gate(draft.channel, spots[1]["center"], spots[1]["radius"], leaving=False)
    assert math.dist(start.a, start.b) == pytest.approx(16.0, abs=0.05)      # spans the corridor
    assert math.dist(finish.a, finish.b) == pytest.approx(16.0, abs=0.05)
    assert start.n == pytest.approx((-1, 0), abs=0.01)       # leaving the top right circle to the left
    assert finish.n == pytest.approx((0, 1), abs=0.01)       # entering the bottom left circle downwards
    assert 12 < math.dist(start.mid, spots[0]["center"]) < 17


def test_gate_from_taps_snaps_to_the_walls(draft):
    gate = gate_from_taps(draft.channel, (330.0, 28.0), (330.4, 35.0))
    assert math.dist(gate.a, gate.b) == pytest.approx(16.0, abs=0.1)
    start = orient(gate, TOP_RIGHT, away=True)
    assert start.n[0] < -0.9
    assert orient(gate, TOP_RIGHT, away=False).n[0] > 0.9
    with pytest.raises(ValueError):
        gate_from_taps(draft.channel, (5.0, 5.0), (6.0, 5.0))    # in solid wood: plate corner


# ---------------------------------------------------------------------- path
@pytest.fixture(scope="module")
def draft_path(draft, draft_channel):
    spots = find_wide_spots(draft.channel, 16.0)
    start_gate = suggest_gate(draft.channel, spots[0]["center"], spots[0]["radius"], True)
    finish_gate = suggest_gate(draft.channel, spots[1]["center"], spots[1]["radius"], False)
    path = plan_path(draft_channel.allowed, 1.5, spots[0]["center"], spots[1]["center"],
                     start_gate, finish_gate)
    return path, start_gate, finish_gate


def test_path_connects_the_circles_inside_the_area(draft_channel, draft_path):
    path, _, _ = draft_path
    assert path.points[0] == pytest.approx(TOP_RIGHT, abs=0.5)
    assert path.points[-1] == pytest.approx(BOTTOM_LEFT, abs=0.5)
    line = LineString(path.points)
    assert draft_channel.allowed.covers(line)
    assert draft_channel.allowed.buffer(-1.5).covers(line)      # keeps the extra margin
    assert 900 < path.length < 2500
    assert path.length == pytest.approx(line.length)


def test_path_has_waypoints_on_both_gates(draft_path):
    path, start_gate, finish_gate = draft_path
    assert 0 < path.start_index < path.finish_index < len(path.points) - 1
    for gate, index in ((start_gate, path.start_index), (finish_gate, path.finish_index)):
        assert LineString([gate.a, gate.b]).distance(Point(path.points[index])) < 1e-6
    assert 0 < path.timed_length < path.length
    assert path.timed_length == pytest.approx(
        LineString(path.points[path.start_index:path.finish_index + 1]).length)


def test_path_is_shorter_than_any_detour_and_roundtrips(draft_path):
    path, _, _ = draft_path
    again = type(path).from_dict(path.to_dict())
    assert again.start_index == path.start_index and len(again.points) == len(path.points)
    assert again.length == pytest.approx(path.length, abs=0.01)
    # Lower bound: straight line between the circles.
    assert path.length > math.dist(TOP_RIGHT, BOTTOM_LEFT)


def test_unreachable_goal_raises(draft):
    cut = Channel(draft.channel, pin_diameter=14, wall_tolerance=3.0, anchor=TOP_RIGHT)
    with pytest.raises(PathError):
        plan_path(cut.allowed, 0.0, TOP_RIGHT, BOTTOM_LEFT, None, None)


def test_estimate_time():
    assert estimate_time(0, 100) == 0
    assert estimate_time(1000, 250, 1000) == pytest.approx(4.25)
    assert estimate_time(10, 250, 1000) == pytest.approx(0.2)        # never reaches full speed


# ------------------------------------------------------------------- runtime
def test_runtime_of_the_draft(draft_svg):
    runtime = LabyrinthRuntime({"id": 1, "name": "Entwurf 1", "svg": draft_svg}, 8, 1.0)
    assert runtime.min_width == pytest.approx(16.0, abs=0.1)
    assert runtime.warnings == []
    assert runtime.gates_suggested and not runtime.ready          # path still missing
    data = runtime.to_client()
    assert data["island_count"] == 2 and len(data["holes"]) == 4
    assert data["start_point"] == pytest.approx(TOP_RIGHT, abs=0.5)


def test_runtime_warns_about_narrow_channels(draft_svg):
    runtime = LabyrinthRuntime({"id": 1, "name": "x", "svg": draft_svg}, 14, 3.0)
    assert any("schmalste Stelle" in w for w in runtime.warnings)
    assert any("Engstellen" in w for w in runtime.warnings)
