"""Admin: drive to an exact coordinate in the base or plate frame."""
from __future__ import annotations

import pytest

from app.game.engine import GameError

from .conftest import run
from .test_game import make_engine


def test_goto_in_the_base_frame_keeps_the_orientation(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            await engine.set_frame("base")
            before = await engine.robot.read_pose()
            target = (before.x + 30.0, before.y - 20.0, before.z + 15.0)
            assert await engine.move_to("base", target) == pytest.approx(list(target), abs=0.01)
            after = await engine.robot.read_pose()
            assert after.xyz == pytest.approx(target, abs=0.05)
            assert after.q == pytest.approx(before.q, abs=1e-6)          # head not turned
            assert engine.robot.home_confirmed is False                    # a visitor run needs home again
        finally:
            await engine.stop()
    run(scenario())


def test_goto_in_the_plate_frame_and_limits(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            retract = engine.robot.retract_z()
            # Above the plate surface, inside the plate outline: allowed.
            await engine.move_to("plate", (120.0, 150.0, retract))
            assert engine.robot.commanded == pytest.approx((120.0, 150.0, retract), abs=0.01)
            # Outside the plate: refused by the plate guard, nothing moves.
            with pytest.raises(GameError):
                await engine.move_to("plate", (900.0, 150.0, retract))
            assert engine.robot.commanded == pytest.approx((120.0, 150.0, retract), abs=0.01)
            # Outside the robot's workspace box in the base frame: refused as well.
            with pytest.raises(GameError, match="Arbeitsraum"):
                await engine.move_to("base", (5000.0, 0.0, 300.0))
            # Bad input.
            for bad in [(1, 2), ("a", 2, 3), (1, float("nan"), 3), None]:
                with pytest.raises(GameError):
                    await engine.move_to("base", bad)
            with pytest.raises(GameError):
                await engine.move_to("world", (1, 2, 3))
        finally:
            await engine.stop()
    run(scenario())
