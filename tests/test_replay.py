"""Replays: every run's path is recorded; it can be shown virtually or driven again by the robot."""
from __future__ import annotations

import pytest

from app.game.engine import GameError
from app.game.state_machine import State

from .conftest import run
from .test_game import hold, make_engine, wait_for

S = State


async def finished_run(engine, name="Lena"):
    await engine.start_run(name, 2010)
    await wait_for(engine, S.ARMED)
    await hold(engine, ["d"], lambda: engine.sm.state in (S.FINISHED, S.RETURNING_HOME, S.IDLE), timeout=30)
    run_id = engine.result["run_id"]
    await wait_for(engine, S.IDLE, timeout=30)
    return run_id


def test_path_is_recorded_and_can_be_replayed_with_approval(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            run_id = await finished_run(engine)
            data = engine.replay_data(run_id)
            points = data["path"]["points"]
            assert data["name"] == "Lena" and data["end"] == "finished" and len(points) > 10
            assert points[0][0] == 0 and all(b[0] >= a[0] for a, b in zip(points, points[1:]))
            assert data["path"]["start_ms"] < data["path"]["finish_ms"]
            assert engine.map_data()["channel"]
            runs_before = len(engine.db.list_runs(engine.lab.id))

            # A visitor at the stats iPad asks, an admin approves.
            await engine.request_replay(run_id)
            assert engine.sm.state == S.AUTO_REQUESTED
            assert engine.snapshot()["replay"]["requested"] is True
            seen = []
            original = engine.robot.move_plate

            async def spy(x, y, z, speed, zone, kind):
                seen.append((round(x, 1), round(y, 1)))
                return await original(x, y, z, speed, zone, kind)
            engine.robot.move_plate = spy
            await engine.start_auto()
            assert engine.snapshot()["run"]["kind"] == "replay"
            await wait_for(engine, S.IDLE, timeout=40)
            recorded = {(p[1], p[2]) for p in points}
            hits = sum(point in recorded for point in seen)
            assert hits >= 0.8 * (len(points) - 1)                     # drove the recorded points
            assert len(engine.db.list_runs(engine.lab.id)) == runs_before  # a replay is no new entry
            assert engine.snapshot()["replay"] is None
        finally:
            await engine.stop()
    run(scenario())


def test_replay_request_can_be_rejected_and_admin_can_start_directly(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            run_id = await finished_run(engine, "Max")
            await engine.request_replay(run_id)
            await engine.reject_auto()
            assert engine.sm.state == S.IDLE and engine.snapshot()["replay"] is None

            await engine.start_replay(run_id)                   # admin: right away
            assert engine.sm.state == S.AUTO_RUN
            await engine.abort()                                # and can stop it any time
            await wait_for(engine, S.IDLE, timeout=20)
            assert engine.snapshot()["replay"] is None
        finally:
            await engine.stop()
    run(scenario())


def test_given_up_runs_are_recorded_and_runs_without_path_are_refused(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            await engine.start_run("Mia", 2012)
            await wait_for(engine, S.ARMED)
            await hold(engine, ["d"], lambda: engine.sm.state == S.RUNNING)
            await engine.give_up()
            await wait_for(engine, S.IDLE, timeout=20)
            aborted = engine.db.list_runs(engine.lab.id)[0]
            assert aborted["status"] == "aborted" and aborted["replay"]
            assert engine.replay_data(aborted["id"])["end"] == "aborted"

            old = engine.board.add_finished(engine.lab.id, "Alt", 2000, 50_000)["run_id"]
            with pytest.raises(GameError, match="keine Aufzeichnung"):
                await engine.request_replay(old)
        finally:
            await engine.stop()
    run(scenario())
