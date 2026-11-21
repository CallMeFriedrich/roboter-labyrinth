"""Other plate sizes: the 300 × 300 mm "Heißer Draht" with start/finish frames instead of circles."""
from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString, Point

from app.geometry import frames
from app.geometry.frames import calibrate, quat_to_rotmat
from app.geometry.labyrinth import LabyrinthRuntime
from app.geometry.lines import crossing_fraction
from app.geometry.pathfinding import plan_path
from app.geometry.svg_import import SvgImportError, parse_svg
from app.game.state_machine import State

from .conftest import ROOT, run
from .test_game import make_engine, wait_for

SVG_300 = (ROOT / "tests" / "data" / "Heisser_Draht_300.svg").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def plate():
    return parse_svg(SVG_300)


@pytest.fixture(scope="module")
def runtime():
    return LabyrinthRuntime({"id": 1, "name": "300", "svg": SVG_300}, 8.0, 1.0)


def test_300_plate_is_recognised(plate):
    assert (plate.width, plate.height) == (300, 300)
    assert plate.holes == [(7.5, 7.5), (292.5, 7.5), (7.5, 292.5), (292.5, 292.5)]
    assert plate.warnings == []
    assert len(plate.channel.interiors) == 0
    assert plate.channel.area == pytest.approx(7433.0, abs=1.0)
    assert set(plate.markers) == {"start", "finish"}
    assert len(plate.engraving) == 2                      # checkerboards + logo, preview only


def test_gates_come_from_the_drawn_frames(runtime):
    assert runtime.warnings == []
    assert runtime.min_width == pytest.approx(15.0, abs=0.1)
    s, f = runtime.start_gate, runtime.finish_gate
    # The frames sit at x = 236 (top right) and x = 64 (bottom left), across horizontal corridors.
    assert s.a[0] == pytest.approx(236, abs=0.01) and s.b[0] == pytest.approx(236, abs=0.01)
    assert f.a[0] == pytest.approx(64, abs=0.01) and f.b[0] == pytest.approx(64, abs=0.01)
    assert abs(s.a[1] - s.b[1]) == pytest.approx(15.0, abs=0.1)        # wall to wall
    # Start area is the dead end right of the start frame, finish area left of the finish frame.
    assert runtime.start_point[0] > 236 and runtime.finish_point[0] < 64
    assert runtime.channel.contains(runtime.channel.snap(runtime.start_point))
    # Driving out of the start area crosses the start gate forwards, driving back does not.
    out = (runtime.start_point, (220.0, runtime.start_point[1]))
    assert crossing_fraction(s, *out) is not None
    assert crossing_fraction(s, out[1], out[0]) is None


def test_shortest_path_stays_inside(runtime):
    path = plan_path(runtime.channel.allowed, 1.5, runtime.start_point, runtime.finish_point,
                     runtime.start_gate, runtime.finish_gate)
    assert path.start_index is not None and path.finish_index is not None
    assert 350 < path.length < 520
    assert runtime.channel.allowed.buffer(1e-6).covers(LineString(path.points))


def test_calibration_uses_the_plate_size():
    rng = np.random.default_rng(3)
    q = rng.normal(size=4)
    rot = quat_to_rotmat(q / np.linalg.norm(q))
    origin = np.array([420.0, -150.0, 480.0])
    holes = frames.holes_plate(300, 300)
    assert holes[4] == (292.5, 292.5)
    p1, p2, p3, p4 = (origin + rot @ np.array([x, y, 0.0]) for x, y in holes.values())
    result = calibrate(p1, p2, p3, p4, 300, 300)
    assert result.warnings == [] and result.check_error < 1e-9
    assert (result.expected_12, result.expected_13) == (285.0, 285.0)
    assert np.allclose(result.frame.origin, origin, atol=1e-9)
    # The same points against the 400 mm defaults are flagged, not silently accepted.
    assert len(calibrate(p1, p2, p3, p4).warnings) == 3


def test_plate_size_limits():
    tiny = SVG_300.replace('viewBox="0 0 300 300"', 'viewBox="0 0 50 50"', 1)
    with pytest.raises(SvgImportError):
        parse_svg(tiny)


def test_auto_run_in_the_simulator_on_the_300_plate():
    async def scenario():
        engine = await make_engine(SVG_300)
        try:
            assert engine.lab.geometry.width == 300 and engine.why_not() is None
            assert engine.admin_snapshot()["admin"]["active_labyrinth"]["size"] == [300, 300]
            await engine.start_auto()
            await wait_for(engine, State.RETURNING_HOME, timeout=40)
            assert engine.auto_result and engine.auto_result["time_ms"] > 0
            await wait_for(engine, State.IDLE, timeout=40)
            assert engine.robot.at_home
        finally:
            await engine.stop()
    run(scenario())


def test_simulator_hole_positions_follow_the_plate():
    async def scenario():
        engine = await make_engine(SVG_300)
        try:
            await engine.sim_goto_hole(4)
            pose = await engine.robot.read_pose()
            sim = engine.config.sim
            plate = frames.Frame.from_list([*sim.plate_origin, *sim.plate_quat])
            assert np.allclose(pose.xyz, plate.to_parent((292.5, 292.5, 0.0)), atol=0.05)
        finally:
            await engine.stop()
    run(scenario())
