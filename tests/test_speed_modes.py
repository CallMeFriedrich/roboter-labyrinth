"""Visitor speed modes (Langsam / Normal / Turbo), switching wall detection off, the logo."""
from __future__ import annotations

import pytest

from app.game.engine import GameError
from app.game.state_machine import State
from app.geometry.svg_import import parse_svg

from .conftest import ROOT, run
from .test_game import hold, make_engine, wait_for

S = State


def test_speed_mode_is_chosen_before_the_start_and_drives_the_arm(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            await engine.patch_settings({"speed_slow": 20.0, "visitor_speed": 60.0, "speed_turbo": 140.0})
            snap = engine.snapshot()
            assert snap["speed_mode"] == "normal"
            assert snap["speeds"] == {"slow": 20.0, "normal": 60.0, "turbo": 140.0}
            with pytest.raises(GameError):
                engine.set_speed_mode("warp")

            engine.set_speed_mode("turbo")
            assert engine.visitor_speed() == 140.0
            await engine.start_run("Lena", 2009)
            with pytest.raises(GameError):                  # no switching during the run
                engine.set_speed_mode("slow")
            await wait_for(engine, S.ARMED)
            seen = []
            original = engine.robot.move_plate

            async def spy(x, y, z, speed, zone, kind):
                if kind == "visitor":
                    seen.append(speed)
                return await original(x, y, z, speed, zone, kind)
            engine.robot.move_plate = spy
            await hold(engine, ["d"], lambda: engine.sm.state in (S.FINISHED, S.RETURNING_HOME, S.IDLE), timeout=30)
            assert seen and set(seen) == {140.0}                # the arm really ran in turbo
            assert engine.result is None or engine.result["speed_mode"] == "turbo"
            await wait_for(engine, S.IDLE, timeout=30)
            assert engine.snapshot()["speed_mode"] == "normal"  # back to normal after a finished run
        finally:
            await engine.stop()
    run(scenario())


def test_speed_mode_survives_a_given_up_run(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            engine.set_speed_mode("slow")
            await engine.start_run("Max", 2008)
            await wait_for(engine, S.ARMED)
            assert engine.snapshot()["speed_mode"] == "slow"
            await engine.give_up()
            await wait_for(engine, S.IDLE, timeout=20)
            assert engine.snapshot()["speed_mode"] == "slow"    # only a finished run resets it
        finally:
            await engine.stop()
    run(scenario())


def test_wall_detection_can_be_switched_off(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            await engine.patch_settings({"wall_tolerance": -6.0, "wall_abort_depth": 6.0, "wall_abort": "off"})
            with pytest.raises(GameError):
                await engine.patch_settings({"wall_abort": "vielleicht"})
            await engine.start_run("Max", 2008)
            await wait_for(engine, S.ARMED)
            await hold(engine, ["d"], lambda: engine.sm.state == S.RUNNING)
            for _ in range(20):
                engine.set_keys(["w"])
                await __import__("asyncio").sleep(0.05)
            assert engine.sm.state == S.RUNNING                  # deep in the wall, but no abort
            assert engine.lab.channel.wall_depth(engine.robot.commanded[:2]) > 5.5
            await engine.abort()
            await wait_for(engine, S.IDLE, timeout=20)
        finally:
            await engine.stop()
    run(scenario())


def test_logo_is_only_the_logo_not_the_start_finish_checkerboards():
    svg = (ROOT / "tests" / "data" / "Heisser_Draht_300.svg").read_text(encoding="utf-8")
    geometry = parse_svg(svg)
    assert len(geometry.engraving) == 2 and len(geometry.logo) == 1
    x0, y0, x1, y1 = geometry.logo_bounds
    assert (x1 - x0) < 110 and (y1 - y0) < 40                  # the TFO logo, about 100 × 34 mm
