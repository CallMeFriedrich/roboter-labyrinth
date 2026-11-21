"""Protocol formatting and the client against the fake controller (CLAUDE.md §12, M1)."""
from __future__ import annotations

import asyncio

import pytest

from app.robot import protocol
from app.robot.protocol import AbbClient, CommandRejected, ConnectionLost, LoggerStream
from tools.fake_controller import FakeController

from .conftest import run


def test_pose_format_matches_abb_py():
    text = protocol.format_pose([474, -12.34, 350.06], [0.707, 0, 0.707, 0])
    assert text == "+00474.0 -00012.3 +00350.1 +0.70700 +0.00000 +0.70700 +0.00000"
    assert protocol.build_message(1, text) == b"01 " + text.encode() + b" #"


def test_other_formats():
    assert protocol.format_joints([0, 45, 0, 0, -45, 105]) == \
        "+0000.00 +0045.00 +0000.00 +0000.00 -0045.00 +0105.00"
    assert protocol.format_speed(100, 50) == "+00100.0 +0050.00 +00050.0 +0050.00"
    assert protocol.format_zone("z1") == "0 +01.0000 +01.0000 +00.1000"
    assert protocol.format_zone("fine") == "1 +00.0000 +00.0000 +00.0000"
    assert protocol.build_message(0) == b"00 #"
    assert protocol.build_message(98) == b"98 #"


def test_messages_fit_into_a_rapid_string():
    text = protocol.format_pose([-999.9, -999.9, -999.9], [-0.5, -0.5, -0.5, -0.5])
    assert len(protocol.build_message(30, text)) <= 80
    with pytest.raises(ValueError):
        protocol.format_pose([1, 2], [1, 0, 0, 0])


def test_logger_parse():
    chunk = ("# 0 2026-11-18 10:11:12 12.34 474.0 0.0 350.0 0.707 0.000 0.707 0.000"
             "# 1 2026-11-18 10:11:12 12.44 0 45 0 0 -45 0")
    parsed = LoggerStream.parse(chunk)
    assert parsed[0] == (0, [474.0, 0.0, 350.0, 0.707, 0.0, 0.707, 0.0])
    assert parsed[1][0] == 1 and len(parsed[1][1]) == 6


async def _with_controller(test, **kwargs):
    controller = FakeController(port=0, time_scale=20.0, **kwargs)
    await controller.start()
    client = AbbClient("127.0.0.1", controller.port, timeout=5.0)
    try:
        await asyncio.to_thread(client.connect)
        await test(controller, client)
    finally:
        await asyncio.to_thread(client.close)
        await controller.stop()


def test_client_speaks_all_codes():
    async def scenario(controller, client):
        call = asyncio.to_thread
        assert await call(client.ping) >= 0                                          # 0
        assert await call(client.robot_info) == ["120-FAKE", "ROBOTWARE_6.00.0000", "IRB 120-3/0.6"]  # 98
        await call(client.set_tool, [0, 0, 100], [1, 0, 0, 0])                      # 6
        await call(client.set_workobject, [0, 0, 0], [1, 0, 0, 0])                  # 7
        await call(client.set_speed, 200.0)                                          # 8
        await call(client.set_zone, "fine")                                          # 9
        await call(client.move_joints, [0, 45, 0, 0, -45, 0])                        # 2
        assert await call(client.get_joints) == [0, 45, 0, 0, -45, 0]                # 4
        await call(client.move_cartesian, [400, 10, 300], [0.707, 0, 0.707, 0])      # 1
        xyz, quat = await call(client.get_cartesian)                                 # 3
        assert xyz == pytest.approx([400, 10, 300], abs=0.01)
        assert quat == pytest.approx([0.707, 0, 0.707, 0], abs=0.001)
        await call(client.buffer_clear)                                              # 31
        for y in (20, 30, 40):
            await call(client.buffer_add, [400, y, 300], [0.707, 0, 0.707, 0])       # 30
        assert await call(client.buffer_len) == 3                                    # 32
        await call(client.set_zone, "z1")
        await call(client.buffer_execute)                                            # 33
        xyz, _ = await call(client.get_cartesian)
        assert xyz == pytest.approx([400, 40, 300], abs=0.01)
        assert client.last_latency > 0 and len(client.latencies) > 10
    run(_with_controller(scenario))


def test_moves_are_in_the_work_object():
    async def scenario(controller, client):
        call = asyncio.to_thread
        await call(client.set_zone, "fine")
        await call(client.set_speed, 500.0)
        # Plate of the simulator: origin (450|-200|550), x = +Y, y = -Z, z = -X of the base.
        await call(client.set_workobject, [450, -200, 550], [0.5, -0.5, -0.5, 0.5])
        await call(client.move_cartesian, [100, 50, 0], [0, 1, 0, 0])
        assert list(controller.model.pos) == pytest.approx([450, -100, 500], abs=1e-6)
        xyz, _ = await call(client.get_cartesian)
        assert xyz == pytest.approx([100, 50, 0], abs=0.01)
    run(_with_controller(scenario))


def test_fine_move_takes_time_and_zone_returns_earlier():
    async def scenario(controller, client):
        call = asyncio.to_thread
        controller.model.time_scale = 1.0
        await call(client.set_speed, 200.0)
        await call(client.set_zone, "fine")
        await call(client.move_cartesian, [374, 0, 400], [1, 0, 0, 0])       # 20 mm from home
        fine = client.last_latency
        await call(client.set_zone, "z10")
        await call(client.move_cartesian, [374, 0, 420], [1, 0, 0, 0])
        zone = client.last_latency
        assert fine > 0.15            # rest to rest: 2·sqrt(20/1000) ≈ 0.28 s
        assert zone < fine
    run(_with_controller(scenario))


def test_wrong_parameter_count_is_rejected():
    async def scenario(controller, client):
        with pytest.raises(CommandRejected):
            await asyncio.to_thread(client.request, 1, "+00100.0 +00100.0")
        with pytest.raises(CommandRejected):
            await asyncio.to_thread(client.request, 0, "+00001.0")
        with pytest.raises(CommandRejected):
            await asyncio.to_thread(client.request, 77)
        await asyncio.to_thread(client.ping)          # still in sync afterwards
    run(_with_controller(scenario))


def test_connection_drop_raises_and_reconnect_works():
    async def scenario(controller, client):
        controller.drop_next = True
        with pytest.raises(ConnectionLost):
            await asyncio.to_thread(client.ping)
        assert not client.connected
        await asyncio.to_thread(client.connect)
        await asyncio.to_thread(client.ping)
    run(_with_controller(scenario))


def test_no_server_raises():
    client = AbbClient("127.0.0.1", 1, connect_timeout=0.5)
    with pytest.raises(ConnectionLost):
        client.connect()
