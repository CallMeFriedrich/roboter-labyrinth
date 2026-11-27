"""Idle show: forward kinematics, collision checks and the automatic start when nobody plays."""
from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest

from app.game import idle_show
from app.game.engine import GameError
from app.game.state_machine import State
from app.geometry.frames import Frame
from app.robot.kinematics import forward

from .conftest import run
from .test_game import make_engine, wait_for

S = State
# The real set-up from the robot appointment (home, tool for the spring rod, measured plate).
HOME = [0.0, -5.8, 54.72, 0.06, 41.02, -0.07]
TOOL = (-140.0, 0.0, 30.0)
PLATE = Frame.from_list([459.19266, 188.74642, 472.55252, 0.502, -0.50201, 0.49485, -0.50111])


def test_forward_kinematics_matches_the_manual_and_the_real_home():
    zero = forward([0, 0, 0, 0, 0, 0])
    assert np.allclose(zero.wrist, [302, 0, 630])               # manual: wrist centre A (302 | 630)
    assert np.allclose(zero.flange_rot[:, 2], [1, 0, 0])        # tool0 points forward
    home = forward(HOME, TOOL)
    assert np.allclose(home.flange_rot[:, 2], [0, 0, -1], atol=0.01)   # flange points down at home
    # The pen tip stands about 10 cm in front of the middle of the plate.
    u, v, n = PLATE.to_local(home.tcp)
    assert 140 < u < 160 + 40 and 180 < v < 215 and -110 < n < -85
    assert forward([90, 0, 0, 0, 0, 0]).wrist[1] == pytest.approx(302)   # axis 1 turns to the left


def test_plan_with_the_real_setup_is_completely_safe():
    moves = idle_show.plan(HOME, TOOL, PLATE, 300, 300)
    assert len(moves) >= 10 and all(m.safe for m in moves), [m.reason for m in moves if not m.safe]


def test_moves_towards_the_plate_or_table_are_refused():
    box = idle_show.PlateBox(PLATE, 300, 300)
    assert idle_show.check_move(HOME, [0, 30, 20, 0, 40, 0], TOOL, box) == "zu nah an der Platte"
    assert idle_show.check_move(HOME, [0, 100, 60, 0, 0, 0], TOOL, box) != ""
    assert idle_show.check_move(HOME, [0, -40, 30, 0, 60, 0], TOOL, box) == ""
    # A plate right in front of the robot: nothing reaching forward is allowed.
    near = Frame.from_list([300, 150, 450, *PLATE.quat])
    moves = idle_show.plan([0, -30, 40, 0, 50, 0], TOOL, near, 300, 300)
    assert not all(m.safe for m in moves)


def real_setup(engine):
    """Home, tool and calibration of the real exhibit (the simulator's own plate stands elsewhere)."""
    engine.db.set_setting("home_joints", HOME)
    engine.db.set_setting("tool", [*TOOL, 0.7071068, 0.0, -0.7071068, 0.0])
    engine.db.add_calibration([None] * 4, PLATE.as_list(), [*TOOL, 0.7071068, 0.0, -0.7071068, 0.0])


def test_the_simulators_own_plate_position_blocks_the_show(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            with pytest.raises(GameError, match="frei von der Platte"):
                await engine.start_show()
        finally:
            await engine.stop()
    run(scenario())


def test_show_runs_when_idle_and_a_visitor_start_stops_it(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        real_setup(engine)
        try:
            status = engine.show_status()
            assert status["total"] > 0 and status["safe"] >= idle_show.MIN_SAFE_MOVES
            seen = []
            original = engine.robot.move_joints_at

            async def spy(joints, speed):
                seen.append(list(joints))
                return await original(joints, speed)
            engine.robot.move_joints_at = spy

            # Nobody played for longer than the set time -> the show starts by itself.
            await engine.patch_settings({"idle_show": "on", "idle_show_min": 1})
            engine.idle_since = time.monotonic() - 61
            for _ in range(60):
                if engine.show_running:
                    break
                await asyncio.sleep(0.1)
            assert engine.show_running and engine.snapshot()["show"] is True
            assert engine.why_not() is None                      # visitors may start anyway
            await asyncio.sleep(0.3)

            # A visitor presses Start: current move ends, home, then the run begins.
            await engine.start_run("Lena", 2010)
            assert not engine.show_running and seen
            safe = [m.joints for m in engine.show_plan() if m.safe]
            assert all(j in safe for j in seen)                   # only checked moves were driven
            assert seen[-1] == idle_show.UPRIGHT                  # interrupted: back over the upright pose
            await wait_for(engine, S.ARMED, timeout=20)
            await engine.abort()
            await wait_for(engine, S.IDLE, timeout=20)
        finally:
            await engine.stop()
    run(scenario())


def test_admin_can_trigger_the_show_and_it_ends_at_home(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        real_setup(engine)
        try:
            await engine.start_show()                             # works although "Automatisch" is off
            with pytest.raises(GameError):
                await engine.start_show()                         # only once at a time
            for _ in range(400):
                if not engine.show_running:
                    break
                await asyncio.sleep(0.05)
            assert not engine.show_running and engine.robot.at_home
            assert engine.sm.state == S.IDLE
        finally:
            await engine.stop()
    run(scenario())


def test_full_span_needs_a_large_enough_free_circle():
    full = idle_show.plan(HOME, TOOL, PLATE, 300, 300, radius=750)
    stretch = [m for m in full if "ausstrecken" in m.name]
    assert len(stretch) == 2 and all(m.safe for m in stretch)
    # Fully stretched the pen tip is about 67 cm from the robot axis.
    tip = forward([90, 85, -85, 0, 0, 0], TOOL).tcp
    assert 650 < float(np.hypot(tip[0], tip[1])) < 700
    small = idle_show.plan(HOME, TOOL, PLATE, 300, 300, radius=600)
    skipped = [m for m in small if not m.safe]
    assert {m.name for m in skipped} == {"Links ganz ausstrecken", "Rechts ganz ausstrecken"}
    assert all(m.reason == "braucht mehr freien Umkreis" for m in skipped)
    # Every safe pose can go back to the upright pose, and the upright pose home.
    box = idle_show.PlateBox(PLATE, 300, 300)
    assert idle_show.check_move(idle_show.UPRIGHT, HOME, TOOL, box) == ""
    for m in full:
        assert idle_show.check_move(m.joints, idle_show.UPRIGHT, TOOL, box) == ""


def test_two_styles_full_span_and_compact(simple_svg):
    compact = idle_show.plan(HOME, TOOL, PLATE, 300, 300, radius=520, style="compact")
    assert all(m.safe for m in compact) and not any("ausstrecken" in m.name or "oben" in m.name for m in compact)
    full = idle_show.plan(HOME, TOOL, PLATE, 300, 300, radius=750, style="full")
    assert any("ausstrecken" in m.name for m in full)

    async def scenario():
        engine = await make_engine(simple_svg)
        real_setup(engine)
        try:
            assert engine.show_status()["total"] == len(full)
            await engine.patch_settings({"idle_show_style": "compact"})
            assert engine.show_status()["total"] == len(compact)       # switching changes the plan
            with pytest.raises(GameError):
                await engine.patch_settings({"idle_show_style": "wild"})
        finally:
            await engine.stop()
    run(scenario())


def test_automatic_show_loops_without_pause_until_somebody_comes(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        real_setup(engine)
        try:
            count = []
            original = engine.robot.move_joints_at

            async def spy(joints, speed):
                count.append(1)
                return await original(joints, speed)
            engine.robot.move_joints_at = spy
            per_round = sum(m.safe for m in engine.show_plan())
            await engine.patch_settings({"idle_show": "on", "idle_show_min": 1, "idle_show_speed": 250})
            engine.idle_since = time.monotonic() - 61
            for _ in range(600):                                 # wait for more than two rounds
                if len(count) > 2 * per_round + 2:
                    break
                await asyncio.sleep(0.05)
            assert engine.show_running and len(count) > 2 * per_round   # still going, no pause
            engine.touch()                                       # somebody types their name
            for _ in range(200):
                if not engine.show_running:
                    break
                await asyncio.sleep(0.05)
            assert not engine.show_running and engine.robot.at_home
        finally:
            await engine.stop()
    run(scenario())


def test_controller_joint_limits_from_the_config_are_respected():
    tight = [[-165, 165], [-110, 70], [-60, 70], [-160, 160], [-120, 120], [-400, 400]]
    moves = idle_show.plan(HOME, TOOL, PLATE, 300, 300, radius=750, style="full", limits=tight)
    skipped = {m.name for m in moves if not m.safe}
    assert {"Ganz nach oben strecken", "Links ganz ausstrecken", "Rechts ganz ausstrecken"} <= skipped
    assert all(m.reason == "Achsgrenze" for m in moves if not m.safe)
    assert sum(m.safe for m in moves) >= idle_show.MIN_SAFE_MOVES      # the rest still runs


def test_figures_can_be_made_smaller_per_style(simple_svg):
    full = idle_show.plan(HOME, TOOL, PLATE, 300, 300, radius=750, style="full", scale=1.0)
    half = idle_show.plan(HOME, TOOL, PLATE, 300, 300, radius=750, style="full", scale=0.5)
    assert all(m.safe for m in half) and len(half) == len(full)
    # Every axis swings at most half as far from the upright pose.
    for a, b in zip(full, half):
        for v, w, u in zip(a.joints, b.joints, idle_show.UPRIGHT):
            assert abs(w - u) == pytest.approx(abs(v - u) / 2, abs=0.01)
    # Tight controller limits: at 100 % the stretch figures are skipped, at 40 % they fit.
    tight = [[-165, 165], [-110, 70], [-60, 70], [-160, 160], [-120, 120], [-400, 400]]
    assert not all(m.safe for m in idle_show.plan(HOME, TOOL, PLATE, 300, 300, 750, "full", tight, 1.0))
    assert all(m.safe for m in idle_show.plan(HOME, TOOL, PLATE, 300, 300, 750, "full", tight, 0.4))

    async def scenario():
        engine = await make_engine(simple_svg)
        real_setup(engine)
        try:
            await engine.patch_settings({"idle_show_style": "full", "idle_show_scale_full": 40})
            joints = [m.joints for m in engine.show_plan()]
            assert joints == [m.joints for m in idle_show.plan(HOME, TOOL, PLATE, 300, 300, 750, "full",
                                                               None, 0.4)]
            await engine.patch_settings({"idle_show_style": "compact", "idle_show_scale_compact": 100})
            assert engine.show_plan()[1].joints == idle_show.COMPACT[1][1]
            with pytest.raises(GameError):
                await engine.patch_settings({"idle_show_scale_full": 150})
        finally:
            await engine.stop()
    run(scenario())
