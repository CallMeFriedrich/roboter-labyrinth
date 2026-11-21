"""Game engine with the simulator: complete runs, abort, dead man, failures (CLAUDE.md §12)."""
from __future__ import annotations

import asyncio
import time

import pytest

from app.game.engine import GameEngine, GameError
from app.game.state_machine import State
from app.robot.driver_base import Pose

from .conftest import fast_config, run, simple_db

S = State


async def make_engine(svg: str, **settings) -> GameEngine:
    db = simple_db(svg)
    for key, value in settings.items():
        db.set_setting(key, value)
    engine = GameEngine(fast_config(), db, seed=False)
    labyrinth_id = db.list_labyrinths()[0]["id"]
    engine.upload_labyrinth  # (labyrinth was inserted directly; gates are suggested on load)
    runtime = engine.runtime(labyrinth_id)
    start, finish = runtime.gate_records()
    db.update_labyrinth(labyrinth_id, start_line=start, finish_line=finish)
    engine._lab_cache.clear()
    engine.compute_path(labyrinth_id)
    db.set_active_labyrinth(labyrinth_id)
    await engine.start()
    await wait_for(engine, S.IDLE)
    return engine


async def wait_for(engine: GameEngine, *states: State, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while engine.sm.state not in states:
        if time.monotonic() > deadline:
            raise AssertionError(f"state {engine.sm.state} instead of {states}")
        await asyncio.sleep(0.01)


async def hold(engine: GameEngine, keys, until, timeout: float = 15.0) -> None:
    """Press keys with a heartbeat like the visitor client does."""
    deadline = time.monotonic() + timeout
    while not until():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached while holding keys")
        engine.set_keys(keys)
        await asyncio.sleep(0.05)


def test_engine_is_ready_after_start(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            assert engine.why_not() is None
            assert engine.lab.ready and engine.lab.start_point == pytest.approx((60, 200), abs=0.5)
            assert engine.robot.home_confirmed and engine.robot.at_home
            snapshot = engine.snapshot()
            assert snapshot["state"] == "IDLE" and snapshot["can_start"] and snapshot["leaderboard"] == []
            assert engine.admin_snapshot()["admin"]["calibration"]["source"] == "sim"
        finally:
            await engine.stop()
    run(scenario())


def test_admin_can_pause_and_release_visitors(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            checks = {c["key"]: c for c in engine.readiness()}
            assert all(c["ok"] for c in checks.values())

            engine.pause()
            assert engine.why_not() == "Die Besucher sind pausiert."
            assert engine.snapshot()["can_start"] is False
            released = {c["key"]: c for c in engine.readiness()}["released"]
            assert released["ok"] is False and released["fix"] == "release"
            with pytest.raises(GameError):
                await engine.start_run("Lena", 2009)
            with pytest.raises(GameError):
                await engine.request_auto()

            engine.release()
            assert engine.why_not() is None

            # Every missing prerequisite is named, with the step that fixes it.
            engine.robot.home_confirmed = False
            engine._refresh_idle()
            home = {c["key"]: c for c in engine.readiness()}["home"]
            assert home["ok"] is False and home["fix"] == "home" and home["detail"]
            await engine.disconnect()
            checks = {c["key"]: c for c in engine.readiness()}
            assert checks["robot"]["fix"] == "connect" and checks["home"]["fix"] is None
            assert engine.admin_snapshot()["admin"]["readiness"]
        finally:
            await engine.stop()
    run(scenario())


def test_complete_visitor_run(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            states = []
            original = engine._state_changed
            engine._state_changed = lambda old, new: (states.append(new), original(old, new))
            engine.sm._on_change = engine._state_changed

            await engine.start_run("  Lena ", "2009")
            with pytest.raises(GameError):
                await engine.start_run("Max", 2008)           # only one run at a time
            await wait_for(engine, S.ARMED)
            assert engine.robot.commanded == pytest.approx((60, 200, -5), abs=0.5)
            assert engine.timer.elapsed_ms() == 0             # timer waits for the start gate

            await hold(engine, ["d"], lambda: engine.sm.state not in (S.ARMED, S.RUNNING))
            assert engine.result is not None
            assert engine.result["name"] == "Lena" and engine.result["rank"] == 1
            assert engine.result["new_best"] and engine.result["total"] == 1
            # ≈ 111 mm between the gates at 150 mm/s; the step loop is a bit slower.
            assert 500 < engine.result["time_ms"] < 4000
            assert engine.snapshot()["leaderboard"][0]["name"] == "Lena"

            await wait_for(engine, S.IDLE)
            assert engine.result is None and engine.run is None
            assert engine.robot.at_home
            assert states == [S.MOVING_TO_START, S.ARMED, S.RUNNING, S.FINISHED, S.RETURNING_HOME, S.IDLE]
        finally:
            await engine.stop()
    run(scenario())


def test_pen_never_leaves_the_allowed_area(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            seen = []
            move = engine.robot.driver.move_linear

            async def spy(pose: Pose, speed, zone):
                seen.append(pose)
                await move(pose, speed, zone)
            engine.robot.driver.move_linear = spy
            await engine.start_run("Wall", 2000)
            await wait_for(engine, S.ARMED)
            seen.clear()
            # Push into walls in every direction for a while.
            for keys in (["w"], ["w", "d"], ["s", "d"], ["s"], ["a"], ["w", "a"]):
                end = time.monotonic() + 0.4
                await hold(engine, keys, lambda: time.monotonic() > end)
            assert len(seen) > 5
            allowed = engine.lab.channel
            assert all(allowed.contains((p.x, p.y)) for p in seen)
            assert all(p.z == -5 for p in seen)
            await engine.abort()
            await wait_for(engine, S.IDLE)
        finally:
            await engine.stop()
    run(scenario())


def test_dead_man_stops_without_heartbeat(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            await engine.start_run("Stop", 2000)
            await wait_for(engine, S.ARMED)
            engine.set_keys(["d"])                     # one message, then silence
            await asyncio.sleep(1.2)
            x_after_silence = engine.robot.commanded[0]
            assert 60 < x_after_silence < 60 + 150 * 0.3 + 30      # ≈ 300 ms of travel plus a step
            await asyncio.sleep(0.5)
            assert engine.robot.commanded[0] == x_after_silence   # really stopped
            await engine.abort()
            await wait_for(engine, S.IDLE)
        finally:
            await engine.stop()
    run(scenario())


@pytest.mark.parametrize("target", [S.MOVING_TO_START, S.COUNTDOWN, S.ARMED, S.RUNNING])
def test_abort_in_every_phase(simple_svg, target):
    async def scenario():
        engine = await make_engine(simple_svg, countdown_s=2)
        try:
            await engine.start_run("Quit", 2001)
            await wait_for(engine, target, S.ARMED if target == S.RUNNING else target)
            if target == S.RUNNING:
                await hold(engine, ["d"], lambda: engine.sm.state == S.RUNNING)
            await engine.give_up()
            assert engine.sm.state in (S.ABORTING, S.RETURNING_HOME)
            await wait_for(engine, S.IDLE)
            assert engine.robot.at_home and engine.run is None
            assert engine.board.top(engine.lab.id) == []          # no entry
            runs = engine.db.list_runs(engine.lab.id)
            assert [r["status"] for r in runs] == ["aborted"]
            assert engine.why_not() is None                       # next visitor can start
        finally:
            await engine.stop()
    run(scenario())


@pytest.mark.parametrize("method", ["fine", "logger", "analytic"])
def test_auto_run_sets_the_robot_best_time(simple_svg, method):
    async def scenario():
        engine = await make_engine(simple_svg, timing_method=method)
        try:
            await engine.request_auto()
            assert engine.sm.state == S.AUTO_REQUESTED
            assert engine.snapshot()["auto_request"] is not None
            await engine.start_auto()                              # admin approves
            await wait_for(engine, S.RETURNING_HOME)
            assert engine.auto_result["method"] == method and engine.auto_result["new_best"]
            first = engine.auto_result["time_ms"]
            assert 10 < first < 3000
            await wait_for(engine, S.IDLE)
            assert engine.board.robot_best(engine.lab.id) == first
            assert engine.board.top(engine.lab.id) == []           # reference time, no rank
        finally:
            await engine.stop()
    run(scenario())


def test_auto_request_can_be_rejected_and_times_out(simple_svg, monkeypatch):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            await engine.request_auto()
            await engine.reject_auto()
            assert engine.sm.state == S.IDLE
            monkeypatch.setattr("app.game.engine.AUTO_REQUEST_TIMEOUT", 0.2)
            await engine.request_auto()
            await asyncio.sleep(0.5)
            assert engine.sm.state == S.IDLE and engine.auto_request_at is None
        finally:
            await engine.stop()
    run(scenario())


def test_connection_loss_stops_the_game(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            engine.robot.want_connected = False        # keep the monitor from reconnecting at once
            await engine.start_run("Lost", 2002)
            await wait_for(engine, S.ARMED)
            engine.robot.driver.fail_next = True
            engine.set_keys(["d"])
            await wait_for(engine, S.DISCONNECTED)
            assert not engine.robot.connected and not engine.robot.home_confirmed
            assert "Verbindung" in engine.message
            assert engine.run is None and engine.board.top(engine.lab.id) == []
            with pytest.raises(GameError):
                await engine.start_run("Next", 2002)

            # Reconnect: tool/work object are sent again, home must be confirmed (sim: automatic).
            await engine.connect()
            await wait_for(engine, S.IDLE)
            assert engine.why_not() is None
        finally:
            await engine.stop()
    run(scenario())


def test_guard_rejects_targets_outside_the_workspace(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            robot = engine.robot
            await robot.apply_frame("plate")
            with pytest.raises(ValueError, match="außerhalb der Platte"):
                await robot.move_plate(450, 200, 30, 50, "fine", "approach")
            with pytest.raises(ValueError, match="Rückzug"):
                await robot.move_plate(60, 200, 80, 50, "fine", "approach")
            with pytest.raises(ValueError, match="nur im Kanal"):
                await robot.move_plate(300, 300, -5, 50, "fine", "approach")   # into solid wood
            with pytest.raises(ValueError, match="nicht erlaubt"):
                await robot.move_plate(60, 200, 30, 500, "fine", "visitor")    # too fast
            await robot.move_plate(60, 200, 30, 100, "fine", "approach")
            await robot.move_plate(60, 200, -5, 100, "fine", "approach")
            with pytest.raises(ValueError, match="herausziehen"):
                await robot.move_plate(80, 200, 30, 100, "fine", "approach")   # sideways while pulling out
            assert robot.commanded == (60, 200, -5)
            await robot.go_home()
        finally:
            await engine.stop()
    run(scenario())


def test_admin_jog_and_calibration_in_the_simulator(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            for index in (1, 2, 3, 4):
                await engine.sim_goto_hole(index)
                point = await engine.calib_save_point(index)
                assert len(point) == 3
            assert engine.sm.state == S.DISCONNECTED            # home must be confirmed again
            result = engine.calibration_result()
            assert result["warnings"] == [] and result["check_error"] < 0.05
            assert result["distance_12"] == pytest.approx(385, abs=0.05)
            assert result["wobj"][:3] == pytest.approx([450, -200, 550], abs=0.05)
            await engine.calib_activate()
            assert engine.admin_snapshot()["admin"]["calibration"]["source"] == "measured"

            await engine.jog_step("base", [1, 0, 0], 10)
            with pytest.raises(GameError):
                await engine.jog_step("base", [1, 0, 0], 7)      # not an allowed step size
            with pytest.raises(GameError, match="Arbeitsraum"):
                for _ in range(40):
                    await engine.jog_step("base", [1, 0, 0], 10)
            await engine.go_home()
            await wait_for(engine, S.IDLE)
            with pytest.raises(GameError):
                await engine.set_tool([0, 0, 1])
            await engine.set_tool([0, 0, 120, 1, 0, 0, 0])
            assert engine.robot.tool.origin == (0, 0, 120)
        finally:
            await engine.stop()
    run(scenario())


def test_geometry_settings_rebuild_the_path(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            before = engine.lab.channel.inset
            await engine.patch_settings({"wall_tolerance": 2.0})
            assert engine.lab.channel.inset == before + 1.0 and engine.lab.ready
            with pytest.raises(GameError):
                await engine.patch_settings({"visitor_speed": 9999})
            await engine.start_run("Busy", 2003)
            with pytest.raises(GameError):
                await engine.patch_settings({"pin_diameter": 6})     # not during a run
            await engine.patch_settings({"visitor_speed": 60})         # speeds may change any time
            await engine.abort()
            await wait_for(engine, S.IDLE)
        finally:
            await engine.stop()
    run(scenario())
