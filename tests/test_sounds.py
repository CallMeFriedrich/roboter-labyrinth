"""Sounds on the visitor screen: on/off and volume from the admin, test sound."""
from __future__ import annotations

import pytest

from app.game.engine import GameError

from .conftest import run
from .test_game import make_engine


class RecordingHub:
    def __init__(self):
        self.public: list[dict] = []

    async def send_public(self, message: dict) -> None:
        self.public.append(message)

    async def send_admin(self, message: dict) -> None: ...


def test_sound_settings_reach_the_visitor_screen(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            assert engine.snapshot()["sound"] == {"on": True, "volume": 70}
            await engine.patch_settings({"sound": "off", "sound_volume": 35})
            assert engine.snapshot()["sound"] == {"on": False, "volume": 35}
            with pytest.raises(GameError):
                await engine.patch_settings({"sound_volume": 150})
            with pytest.raises(GameError):
                await engine.patch_settings({"sound": "laut"})
        finally:
            await engine.stop()
    run(scenario())


def test_admin_can_play_a_test_sound(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        engine.hub = hub = RecordingHub()
        try:
            await engine.sound_test("record")
            assert {"type": "sound", "name": "record"} in hub.public
            with pytest.raises(GameError):
                await engine.sound_test("explosion")
        finally:
            await engine.stop()
    run(scenario())
