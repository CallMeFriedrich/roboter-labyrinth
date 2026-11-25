"""After one measured hole the other three are predicted and can be approached safely."""
from __future__ import annotations

import numpy as np
import pytest

from app.geometry import frames
from app.geometry.frames import Frame, estimate_holes, rotmat_to_quat

from .conftest import run
from .test_game import make_engine


def rot_about(axis, deg):
    a = np.asarray(axis, float) / np.linalg.norm(axis)
    t = np.radians(deg)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(t) * k + (1 - np.cos(t)) * k @ k


def plate(origin, rot):
    return Frame(tuple(origin), rotmat_to_quat(rot))


# Upright plate square to the robot, visitors on the robot side: ex = −Y, ey = −Z.
UPRIGHT = np.column_stack([[0, -1, 0], [0, 0, -1], [1, 0, 0]])


def measured_from(frame, indices, size=300.0):
    holes = frames.holes_plate(size, size)
    return {i: list(frame.to_parent((*holes[i], 0.0))) for i in indices}


def predicted_error(frame, est, size=300.0):
    holes = frames.holes_plate(size, size)
    return max(np.linalg.norm(est.hole(*holes[i]) - frame.to_parent((*holes[i], 0.0))) for i in holes)


def test_one_hole_is_enough_for_an_upright_plate_square_to_the_robot():
    p = plate((480.0, 150.0, 330.0), UPRIGHT)
    for start in (1, 2, 3, 4):
        est = estimate_holes(measured_from(p, [start]), 300, 300, "robot")
        assert est.used == 1
        assert predicted_error(p, est) < 1e-9
        assert np.dot(est.towards_robot, -np.array([480.0, 0, 330.0])) > 0   # clearance goes to the robot side


def test_visitors_opposite_mirror_left_and_right():
    mirrored = np.column_stack([[0, 1, 0], [0, 0, -1], [-1, 0, 0]])
    p = plate((480.0, -150.0, 330.0), mirrored)
    est = estimate_holes(measured_from(p, [1]), 300, 300, "opposite")
    assert predicted_error(p, est) < 1e-9


def test_two_holes_handle_a_turned_plate_and_three_handle_any_plate():
    turned = plate((470.0, 160.0, 320.0), rot_about([0, 0, 1], 12) @ UPRIGHT)     # yawed, still upright
    est = estimate_holes(measured_from(turned, [1, 2]), 300, 300, "robot")
    assert predicted_error(turned, est) < 1e-9
    # One hole only: a turned plate gives a rough guess, good enough to get close.
    rough = estimate_holes(measured_from(turned, [1]), 300, 300, "robot")
    assert 1.0 < predicted_error(turned, rough) < 90.0

    leaning = plate((470.0, 160.0, 320.0), rot_about([1, 0.3, 0.2], 17) @ UPRIGHT)  # tilted and turned
    two = estimate_holes(measured_from(leaning, [1, 2]), 300, 300, "robot")
    three = estimate_holes(measured_from(leaning, [1, 2, 3]), 300, 300, "robot")
    assert predicted_error(leaning, three) < 1e-9 < predicted_error(leaning, two)
    assert three.used == 3


def test_engine_predicts_and_drives_in_front_of_the_next_hole(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            assert engine.hole_predictions() is None
            sim = engine.config.sim
            true_plate = Frame.from_list([*sim.plate_origin, *sim.plate_quat])
            for index in (1, 2):                                   # measure two holes in the simulator
                await engine.sim_goto_hole(index)
                await engine.calib_save_point(index)
            predictions = engine.admin_snapshot()["admin"]["hole_predictions"]
            assert predictions["1"]["measured"] and not predictions["3"]["measured"]
            assert predictions["3"]["based_on"] == 2

            target = await engine.calib_goto_hole(3)
            pose = await engine.robot.read_pose()
            assert pose.xyz == pytest.approx(target, abs=0.05)
            x, y = frames.holes_plate(*engine._plate_size())[3]
            hole3 = true_plate.to_parent((x, y, 0.0))
            gap = np.linalg.norm(np.asarray(pose.xyz) - hole3)
            assert gap == pytest.approx(20.0, abs=0.5)             # 20 mm in front of the real hole
            # … on the robot's side of the plate, never behind it
            normal = true_plate.rot @ np.array([0.0, 0.0, 1.0])
            side_pen = np.dot(np.asarray(pose.xyz) - hole3, normal)
            side_robot = np.dot(-hole3, normal)
            assert side_pen * side_robot > 0
        finally:
            await engine.stop()
    run(scenario())


def test_take_over_is_refused_while_the_pen_still_waits_in_front_of_the_hole(simple_svg):
    from app.game.engine import GameError

    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            sim = engine.config.sim
            true_plate = Frame.from_list([*sim.plate_origin, *sim.plate_quat])
            for index in (1, 2):
                await engine.sim_goto_hole(index)
                await engine.calib_save_point(index)
            x, y = frames.holes_plate(*engine._plate_size())[3]
            hole3 = true_plate.to_parent((x, y, 0.0))

            await engine.calib_goto_hole(3)                                   # 20 mm in front
            assert engine.admin_snapshot()["admin"]["hole_waiting"]["clearance"] == 20.0
            with pytest.raises(GameError, match="20 mm vor der Bohrung"):
                await engine.calib_save_point(3)
            assert 3 not in engine.calib_points

            await engine.calib_goto_hole(3, 2.0)                              # "Näher ran"
            pose = await engine.robot.read_pose()
            assert np.linalg.norm(np.asarray(pose.xyz) - hole3) == pytest.approx(2.0, abs=0.05)
            with pytest.raises(GameError, match="2 mm vor der Bohrung"):
                await engine.calib_save_point(3)

            await engine.move_to("base", tuple(hole3))                        # the last bit by hand
            assert engine.admin_snapshot()["admin"]["hole_waiting"] is None
            assert await engine.calib_save_point(3) == pytest.approx(list(hole3), abs=0.01)
            with pytest.raises(GameError):
                await engine.calib_goto_hole(3, 7.0)                          # only 20 or 2 mm
        finally:
            await engine.stop()
    run(scenario())
