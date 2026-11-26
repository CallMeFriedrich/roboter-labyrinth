"""Negative wall tolerance (spring rod may press into the wall) and the run ending too deep in a wall."""
from __future__ import annotations

import asyncio

import pytest
from shapely.geometry import LineString

from app.game.engine import GameError
from app.game.state_machine import State
from app.geometry.channel import Channel
from app.geometry.svg_import import parse_svg

from .conftest import run
from .test_game import hold, make_engine, wait_for

S = State


def test_wall_depth_and_negative_tolerance(simple_svg):
    corridor = parse_svg(simple_svg).channel                 # 16 mm corridor, centre line y = 200
    ch = Channel(corridor, pin_diameter=8.0, wall_tolerance=-5.0, anchor=(60, 200))
    assert ch.wall_depth((130, 200)) == pytest.approx(-4.0, abs=0.01)   # pen in the middle: 4 mm room
    assert ch.wall_depth((130, 208)) == pytest.approx(4.0, abs=0.01)    # centre on the wall: half the pen inside
    assert ch.contains((130, 208 + 1.0))                       # −5 mm: centre may be 1 mm in the wall
    assert not ch.contains((130, 208 + 1.5))
    assert ch.wall_depth((130, 209)) == pytest.approx(5.0, abs=0.01)


def test_tolerance_down_to_minus_10_and_auto_path_stays_clear(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            await engine.patch_settings({"wall_tolerance": -10.0, "pin_diameter": 6.0})
            with pytest.raises(GameError):
                await engine.patch_settings({"wall_tolerance": -30.5})     # far beyond any sensible value
            lab = engine.lab
            assert lab.channel.inset == pytest.approx(-7.0)
            assert lab.auto_channel.inset == pytest.approx(3.0)     # robot run: never into a wall
            assert lab.auto_channel.allowed.buffer(1e-6).covers(LineString(lab.path.points))
        finally:
            await engine.stop()
    run(scenario())


def test_run_ends_when_the_pen_is_too_deep_in_a_wall(simple_svg, monkeypatch):
    monkeypatch.setattr("app.game.engine.WALL_HOLD_S", 1.0)
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            await engine.patch_settings({"wall_tolerance": -6.0, "wall_abort_depth": 6.0})
            await engine.start_run("Lena", 2009)
            await wait_for(engine, S.ARMED)
            await hold(engine, ["d"], lambda: engine.sm.state == S.RUNNING)
            # Now steer up into the wall until the run ends.
            await hold(engine, ["w"], lambda: engine.sm.state in (S.ABORTING, S.RETURNING_HOME, S.IDLE))
            snap = engine.snapshot()
            assert snap["state"] == "ABORTING"
            assert snap["notice"] == "Wand berührt – der Roboter bleibt kurz stehen."
            assert snap["result"] is None and snap["wall_hit"]["time_ms"] > 0
            frozen = snap["wall_hit"]["time_ms"]
            assert snap["run"]["running"] is False and snap["run"]["elapsed_ms"] == frozen   # clock stopped
            # The robot stands still where it touched the wall.
            standing = engine.robot.commanded
            await asyncio.sleep(0.5)
            assert engine.robot.commanded == standing and engine.sm.state == S.ABORTING
            assert engine.snapshot()["run"]["elapsed_ms"] == frozen
            await wait_for(engine, S.IDLE, timeout=20)
            assert engine.snapshot()["notice"] is None and engine.snapshot()["wall_hit"] is None
            assert engine.board.top(engine.lab.id) == []                  # no time on the board
            assert [r["status"] for r in engine.db.list_runs(engine.lab.id)] == ["aborted"]
            assert engine.robot.at_home
        finally:
            await engine.stop()
    run(scenario())


def test_abort_off_lets_the_pen_slide_along_the_wall(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            await engine.patch_settings({"wall_tolerance": -6.0, "wall_abort_depth": 0.0})
            await engine.start_run("Max", 2008)
            await wait_for(engine, S.ARMED)
            await hold(engine, ["d"], lambda: engine.sm.state == S.RUNNING)
            for _ in range(20):                                           # pressing into the wall
                engine.set_keys(["w"])
                await asyncio.sleep(0.05)
            assert engine.sm.state == S.RUNNING
            depth = engine.lab.channel.wall_depth(engine.robot.commanded[:2])
            assert 5.5 < depth <= 6.0 + 0.3                                # at the limit, not beyond
            await engine.abort()
            await wait_for(engine, S.IDLE, timeout=20)
        finally:
            await engine.stop()
    run(scenario())


def test_thin_walls_are_reported_only_when_the_pen_could_cross_them():
    from shapely.geometry import box
    from shapely.ops import unary_union
    u_shape = unary_union([box(0, 0, 100, 16), box(0, 26, 100, 42), box(84, 0, 100, 42)])  # 10 mm wall
    assert not Channel(u_shape, 6.0, -2.0).bridged_walls()
    assert Channel(u_shape, 6.0, -10.0).bridged_walls()
    assert not Channel(u_shape, 6.0, 1.0).bridged_walls()



def test_tolerance_that_would_cut_through_a_wall_is_refused(simple_svg):
    from shapely.geometry import box
    from shapely.ops import unary_union

    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            await engine.patch_settings({"pin_diameter": 6.0})
            # Pretend the active labyrinth has two corridors with a 10 mm wall between them.
            engine.lab.geometry.channel = unary_union(
                [box(0, 0, 100, 16), box(0, 26, 100, 42), box(84, 0, 100, 42)])
            with pytest.raises(GameError, match="abkürzen") as refused:
                await engine.patch_settings({"wall_tolerance": -10.0})
            assert "höchstens" in str(refused.value)
            assert engine.settings["wall_tolerance"] != -10.0
            await engine.patch_settings({"wall_tolerance": -3.0})            # still fine
        finally:
            await engine.stop()
    run(scenario())
