"""Calibration keeps the taught pen orientation; errors in the tool offset cancel out."""
from __future__ import annotations

import numpy as np
import pytest

from app.db import Database
from app.geometry import frames
from app.geometry.frames import Frame, calibrate, quat_to_rotmat, rotmat_to_quat
from app.game.engine import GameEngine

from .conftest import fast_config, run


def rot_about(axis, deg):
    a = np.asarray(axis, float) / np.linalg.norm(axis)
    t = np.radians(deg)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(t) * k + (1 - np.cos(t)) * k @ k


def test_wrong_tool_offset_cancels_with_the_taught_orientation():
    # A vertical 300 mm plate in front of the robot, visitors on the far side.
    plate_true = Frame((520.0, 150.0, 330.0), rotmat_to_quat(np.column_stack([[0, -1, 0], [0, 0, -1], [1, 0, 0]])))
    # The head is held level (pen pointing along +x into the plate) for every hole.
    r_flange = rot_about([0, 1, 0], 90) @ rot_about([0, 0, 1], 17)
    q_flange = rotmat_to_quat(r_flange)
    t_true = np.array([73.0, -2.0, 95.0])       # real tip in flange coordinates
    t_wrong = np.array([50.0, -17.0, -16.0])    # what a bad tool teach produced

    holes = frames.holes_plate(300, 300)
    measured = []
    for x, y in holes.values():
        tip = plate_true.to_parent((x, y, 0.0))
        flange = tip - r_flange @ t_true                     # where the flange really is
        measured.append(flange + r_flange @ t_wrong)         # what the controller reports with t_wrong
    result = calibrate(*measured, 300, 300)
    assert result.warnings == [] and result.check_error < 1e-9

    # Drive to a plate point with the taught orientation and the wrong tool …
    plate_meas = result.frame
    q_plate = plate_meas.quat_to_local(q_flange)             # what tool_quat() returns
    for target in [(150.0, 150.0, -5.0), (20.0, 280.0, -5.0), (292.5, 7.5, 0.0)]:
        commanded_tip = plate_meas.to_parent(target)
        r_cmd = quat_to_rotmat(plate_meas.quat_to_parent(q_plate))
        flange = commanded_tip - r_cmd @ t_wrong
        real_tip = flange + r_cmd @ t_true
        # … and the real pen tip is exactly where it should be.
        assert np.allclose(real_tip, plate_true.to_parent(target), atol=1e-9)


def test_engine_records_the_orientation_and_warns_about_a_turned_head(tmp_path):
    async def scenario():
        db = Database(tmp_path / "t.db")
        engine = GameEngine(fast_config(), db, seed=False)
        level = list(rotmat_to_quat(rot_about([0, 1, 0], 90)))
        turned = list(rotmat_to_quat(rot_about([0, 1, 0], 90) @ rot_about([1, 0, 0], 20)))
        plate = Frame((500.0, 150.0, 330.0), rotmat_to_quat(np.column_stack([[0, -1, 0], [0, 0, -1], [1, 0, 0]])))
        for i, (x, y) in frames.HOLES_PLATE.items():
            engine.calib_points[i] = list(plate.to_parent((x, y, 0.0)))
            engine.calib_quats[i] = level
        result = engine.calibration_result()
        assert result["warnings"] == [] and result["orientation_spread_deg"] < 1e-6

        engine.calib_quats[3] = turned
        result = engine.calibration_result()
        assert any("gedreht" in w for w in result["warnings"])
        assert result["orientation_spread_deg"] == pytest.approx(20.0, abs=0.01)

        engine.calib_quats[3] = level
        await engine.calib_activate()
        stored = db.get_active_calibration()
        assert stored["pen_quat"] == pytest.approx(level, abs=1e-6)
        robot = engine.robot
        # The pen keeps the taught orientation, expressed in plate coordinates.
        expected = robot.plate_frame.quat_to_local(level)
        assert np.allclose(np.abs(np.dot(robot.tool_quat(), expected)), 1.0)
        # ex = −y, ey = −z → ez = +x points away from the robot: the visitors see the plate
        # from the robot side, so the pen goes in along +z.
        assert robot.viewer_side() == "robot"
        assert robot.retract_z() < 0 < robot.insert_z()

        # Holes taught in mirrored order (visitors on the far side): ez points to the robot.
        mirrored = Frame((500.0, -150.0, 330.0), rotmat_to_quat(np.column_stack([[0, 1, 0], [0, 0, -1], [-1, 0, 0]])))
        for i, (x, y) in frames.HOLES_PLATE.items():
            engine.calib_points[i] = list(mirrored.to_parent((x, y, 0.0)))
        await engine.calib_activate()
        assert robot.viewer_side() == "opposite"
        assert robot.insert_z() < 0 < robot.retract_z()
    run(scenario())
