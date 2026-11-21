"""Calibration maths, quaternions and side-dependent signs (CLAUDE.md §6, §12)."""
from __future__ import annotations

import math

import numpy as np
import pytest

from app.geometry import frames
from app.geometry.frames import Frame, calibrate, quat_to_rotmat, rotmat_to_quat
from app.settings import Config


def random_rotation(rng) -> np.ndarray:
    q = rng.normal(size=4)
    return quat_to_rotmat(q / np.linalg.norm(q))


def holes_in_base(rot: np.ndarray, origin: np.ndarray) -> list[np.ndarray]:
    return [origin + rot @ np.array([x, y, 0.0]) for x, y in frames.HOLES_PLATE.values()]


def test_quaternion_roundtrip_for_many_rotations():
    rng = np.random.default_rng(1)
    for _ in range(200):
        rot = random_rotation(rng)
        assert np.allclose(quat_to_rotmat(rotmat_to_quat(rot)), rot, atol=1e-12)
    # 180° rotations are the hard case for naive conversions.
    for axis in ([1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [1, 1, 1]):
        a = np.array(axis, dtype=float) / np.linalg.norm(axis)
        rot = 2 * np.outer(a, a) - np.eye(3)
        assert np.allclose(quat_to_rotmat(rotmat_to_quat(rot)), rot, atol=1e-12)


def test_calibration_with_synthetic_points_is_exact():
    rng = np.random.default_rng(7)
    for _ in range(50):
        rot = random_rotation(rng)
        origin = rng.uniform(-500, 500, size=3)
        p1, p2, p3, p4 = holes_in_base(rot, origin)
        result = calibrate(p1, p2, p3, p4)
        assert result.ok
        assert result.check_error < 0.01
        assert np.linalg.norm(np.array(result.frame.origin) - origin) < 0.01
        # Every plate point maps to the right base point: < 0.01 mm.
        for plate in ([0, 0, 0], [400, 400, 0], [200, 123, -5], [31.8, 368.2, 30]):
            expected = origin + rot @ np.array(plate, dtype=float)
            assert np.linalg.norm(result.frame.to_parent(plate) - expected) < 0.01
            assert np.linalg.norm(result.frame.to_local(expected) - plate) < 0.01


def test_calibration_tolerates_a_slightly_skewed_third_point():
    rot, origin = np.eye(3), np.zeros(3)
    p1, p2, p3, p4 = holes_in_base(rot, origin)
    p3 = p3 + np.array([0.8, 0.0, 0.0])            # measured a bit off along x
    result = calibrate(p1, p2, p3, p4)
    assert np.allclose(result.frame.rot, np.eye(3), atol=1e-9)      # ex comes from p1→p2 only
    assert abs(result.skew_deg) > 0.05


def test_calibration_warns_about_outliers():
    p1, p2, p3, p4 = holes_in_base(np.eye(3), np.zeros(3))
    result = calibrate(p1, p2 + np.array([4.0, 0, 0]), p3, p4)
    assert not result.ok and "oben rechts" in result.warnings[0]
    result = calibrate(p1, p2, p3, p4 + np.array([0, 0, 3.0]))
    assert not result.ok and "Kontrollbohrung" in result.warnings[0]
    assert result.check_error == pytest.approx(3.0)
    assert calibrate(p1, p2, p3).check_error is None


def test_calibration_rejects_degenerate_points():
    with pytest.raises(ValueError):
        calibrate([0, 0, 0], [0, 0, 0], [0, 385, 0])
    with pytest.raises(ValueError):
        calibrate([0, 0, 0], [385, 0, 0], [770, 0, 0])


def test_plate_frame_is_right_handed_with_z_away_from_the_visitors():
    # Visitors opposite the robot, plate in front of the robot at x = 450.
    p1, p2, p3 = [450, -192.5, 542.5], [450, 192.5, 542.5], [450, -192.5, 157.5]
    frame = calibrate(p1, p2, p3).frame
    ex, ey, ez = frame.rot[:, 0], frame.rot[:, 1], frame.rot[:, 2]
    assert np.allclose(ex, [0, 1, 0]) and np.allclose(ey, [0, 0, -1])
    assert np.allclose(ez, [-1, 0, 0])             # towards the robot = away from the visitors
    assert np.allclose(frame.origin, [450, -200, 550])


def test_simulator_plate_matches_that_frame():
    sim = Config().sim
    frame = Frame.from_list([*sim.plate_origin, *sim.plate_quat])
    assert np.allclose(frame.to_parent([0, 0, 0]), [450, -200, 550])
    assert np.allclose(frame.to_parent([400, 400, 0]), [450, 200, 150])
    assert np.allclose(frame.rot[:, 2], [-1, 0, 0])


def test_signs_visitors_opposite():
    assert frames.insert_z("opposite", 5) == -5
    assert frames.retract_z("opposite", 30) == 30
    assert frames.z_range("opposite", 5, 30) == (-5, 30)
    assert frames.tool_orientation("opposite") == pytest.approx((0, 1, 0, 0))
    assert np.allclose(frames.tool_axis_in_plate("opposite"), [0, 0, -1])     # pen points against ez
    assert frames.is_inserted("opposite", -5) and frames.is_inserted("opposite", 0)
    assert not frames.is_inserted("opposite", 30)


def test_signs_visitors_on_the_robot_side():
    assert frames.insert_z("robot", 5) == 5
    assert frames.retract_z("robot", 30) == -30
    assert frames.tool_orientation("robot") == pytest.approx((1, 0, 0, 0))
    assert np.allclose(frames.tool_axis_in_plate("robot"), [0, 0, 1])
    assert frames.is_inserted("robot", 5) and not frames.is_inserted("robot", -30)


def test_roll_turns_about_the_pen_axis_only():
    for side in ("opposite", "robot"):
        base = frames.tool_axis_in_plate(side)
        for roll in (-180, -90, 30, 90, 180):
            assert np.allclose(frames.tool_axis_in_plate(side, roll), base, atol=1e-12)
            q = frames.tool_orientation(side, roll)
            assert math.isclose(sum(v * v for v in q), 1.0, abs_tol=1e-12)
    assert frames.tool_orientation("opposite", 90) != pytest.approx(frames.tool_orientation("opposite", 0))


def test_pen_points_at_the_plate_in_base_coordinates():
    """Opposite visitors: in base coordinates the pen must point in +x (towards the plate)."""
    sim = Config().sim
    plate = Frame.from_list([*sim.plate_origin, *sim.plate_quat])
    q_base = plate.quat_to_parent(frames.tool_orientation("opposite"))
    assert np.allclose(quat_to_rotmat(q_base) @ [0, 0, 1], [1, 0, 0], atol=1e-9)
    assert plate.quat_to_local(q_base) == pytest.approx(frames.tool_orientation("opposite"), abs=1e-9)


def test_invalid_side_is_rejected():
    with pytest.raises(ValueError):
        frames.insert_z("left", 5)
