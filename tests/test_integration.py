"""Integration: standard driver ↔ fake controller, complete runs over HTTP + WebSocket (§12)."""
from __future__ import annotations

import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from app.settings import hash_pin
from tools.fake_controller import FakeController

from .conftest import fast_config, simple_db

PIN = "4711"
SIM_PLATE = [450.0, -200.0, 550.0, 0.5, -0.5, -0.5, 0.5]


class ControllerThread:
    """Runs the fake controller in its own event loop, like a robot beside the laptop."""

    def __init__(self, **kwargs):
        self.loop = asyncio.new_event_loop()
        self.controller = FakeController(port=0, time_scale=8.0, **kwargs)
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)

    def __enter__(self) -> FakeController:
        self._thread.start()
        asyncio.run_coroutine_threadsafe(self.controller.start(), self.loop).result(5)
        return self.controller

    def __exit__(self, *exc) -> None:
        asyncio.run_coroutine_threadsafe(self.controller.stop(), self.loop).result(5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(5)


def read_until(ws, predicate, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        message = ws.receive_json()
        if predicate(message):
            return message
    raise AssertionError("expected message did not arrive")


def is_state(*names):
    return lambda m: m.get("type") == "state" and m["state"] in names


@pytest.fixture()
def stack(simple_svg):
    """App with the standard driver, connected to a fake controller; admin is logged in."""
    with ControllerThread(logger_port=0) as controller:
        config = fast_config(ip="127.0.0.1", port=controller.port, logger_port=controller.logger_port,
                             reconnect_interval_s=0.3)
        config.admin.pin_sha256 = hash_pin(PIN)
        db = simple_db(simple_svg)
        db.set_setting("driver", "standard")
        db.add_calibration([None] * 4, SIM_PLATE, [0, 0, 0, 1, 0, 0, 0])
        app = create_app(config, db, seed=False)
        engine = app.state.engine
        labyrinth_id = db.list_labyrinths()[0]["id"]
        start, finish = engine.runtime(labyrinth_id).gate_records()
        db.update_labyrinth(labyrinth_id, start_line=start, finish_line=finish)
        engine._lab_cache.clear()
        engine.compute_path(labyrinth_id)
        db.set_active_labyrinth(labyrinth_id)
        with TestClient(app) as client:
            assert client.post("/api/admin/login", json={"pin": PIN}).status_code == 200
            yield client, controller, engine


def command(client, name, body=None):
    response = client.post(f"/api/admin/cmd/{name}", json=body or {})
    return response.status_code, response.json()


def test_pages_static_files_and_login(stack):
    client, _, _ = stack
    assert "Roboter-Labyrinth" in client.get("/").text
    assert "Betreuung" in client.get("/admin").text
    for path in ("shared/tokens.css", "visitor/visitor.js", "admin/admin.js", "shared/icons.svg",
                 "fonts/InterVariable.woff2"):
        assert client.get(f"/static/{path}").status_code == 200, path
    assert client.get("/api/logo").json()["paths"]
    assert "Statistik" in client.get("/stats").text
    for path in ("stats/stats.js", "stats/stats.css", "shared/logo.js", "visitor/sounds.js"):
        assert client.get(f"/static/{path}").status_code == 200, path
    stats = client.get("/api/stats").json()
    assert set(stats) >= {"profile", "runs", "boards", "year"}
    export = client.get("/api/admin/export.csv")
    assert export.status_code == 200 and export.text.startswith("﻿Platz im Tempo;")
    assert "Bestenliste_Standard_" in export.headers["content-disposition"]

    anonymous = TestClient(client.app)
    assert anonymous.get("/api/admin/state").status_code == 401
    assert anonymous.post("/api/admin/cmd/home").status_code == 401
    assert anonymous.get("/api/admin/export.csv").status_code == 401
    assert anonymous.get("/api/stats").status_code == 200       # the stats iPad needs no login
    assert anonymous.post("/api/admin/login", json={"pin": "0000"}).status_code == 401
    assert anonymous.get("/api/admin/session").json() == {"ok": False}
    with anonymous.websocket_connect("/ws/admin") as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4401            # the panel shows the login again


def test_complete_run_over_websocket(stack):
    client, controller, engine = stack
    state = client.get("/api/admin/state").json()["state"]
    assert state["robot"]["connected"] is True and state["robot"]["driver"] == "standard"
    assert state["state"] == "DISCONNECTED"                  # real robot: home is not confirmed yet
    assert state["admin"]["info"]["robot_type"] == "IRB 120-3/0.6"
    assert state["admin"]["logger"] is True

    with client.websocket_connect("/ws/visitor") as ws:
        assert ws.receive_json() == {"type": "hello", "control": True}
        assert ws.receive_json()["can_start"] is False
        ws.send_json({"type": "start", "name": "Lena", "birth_year": 2009})
        assert ws.receive_json()["type"] == "error"          # not ready: friendly refusal

        assert command(client, "home")[0] == 200             # admin confirms home
        read_until(ws, is_state("IDLE"))

        ws.send_json({"type": "start", "name": "", "birth_year": 2009})
        assert read_until(ws, lambda m: m["type"] == "error")["message"] == "Bitte gib deinen Namen ein."
        ws.send_json({"type": "start", "name": "Lena", "birth_year": 2009})
        read_until(ws, is_state("MOVING_TO_START"))
        read_until(ws, is_state("ARMED"))

        result = None
        seq = 0
        deadline = time.monotonic() + 30
        while result is None and time.monotonic() < deadline:
            seq += 1
            ws.send_json({"type": "keys", "down": ["d"], "seq": seq})     # heartbeat
            time.sleep(0.05)
            while True:
                message = ws.receive_json()
                if message["type"] == "result":
                    result = message
                if message["type"] == "state":
                    break
        assert result is not None, "run did not finish"
        assert result["name"] == "Lena" and result["rank"] == 1 and result["total"] == 1
        final = read_until(ws, is_state("IDLE"))
        assert final["leaderboard"][0]["time_ms"] == result["time_ms"]

    # The controller received real protocol traffic: tool, work object, joint and linear moves.
    codes = {text.split()[0] for text in controller.commands}
    assert {"00", "01", "02", "06", "07", "08", "09", "98"} <= codes
    plate = engine.robot.plate_frame
    assert list(controller.model.wobj.origin) == pytest.approx(list(plate.origin))
    runs = client.get("/api/admin/runs").json()
    assert [(r["name"], r["status"]) for r in runs] == [("Lena", "finished")]


def test_auto_run_with_approval_and_admin_commands(stack):
    client, controller, engine = stack
    assert command(client, "home")[0] == 200
    with client.websocket_connect("/ws/visitor") as visitor, client.websocket_connect("/ws/admin") as admin:
        visitor.receive_json()
        read_until(visitor, is_state("IDLE"))
        assert read_until(admin, is_state("IDLE"))["admin"]["home_confirmed"] is True

        visitor.send_json({"type": "request_auto"})
        assert read_until(admin, is_state("AUTO_REQUESTED"))["auto_request"] is not None
        assert command(client, "auto_start")[0] == 200       # admin approves
        read_until(visitor, is_state("AUTO_RUN"))
        done = read_until(visitor, lambda m: m.get("type") == "state" and m["auto_result"], timeout=30)
        assert done["auto_result"]["new_best"] is True
        idle = read_until(visitor, is_state("IDLE"), timeout=30)
        assert idle["robot_best_ms"] == done["auto_result"]["time_ms"]
        assert idle["leaderboard"] == []

    assert "33" in {text.split()[0] for text in controller.commands}     # buffered path was used
    assert command(client, "settings", {"values": {"visitor_speed": 80}})[0] == 200
    assert command(client, "settings", {"values": {"visitor_speed": 999}})[0] == 400
    assert command(client, "jog_step", {"frame": "plate", "dir": [1, 0, 0], "step": 3})[0] == 400
    assert command(client, "does_not_exist")[0] == 404
    assert command(client, "lab_point", {"id": 1})[0] == 400              # missing fields
    assert command(client, "robot_best_reset")[0] == 200
    assert client.get("/api/admin/state").json()["state"]["robot_best_ms"] is None


def test_reconnect_after_connection_loss(stack):
    client, controller, engine = stack
    assert command(client, "home")[0] == 200
    with client.websocket_connect("/ws/admin") as admin:
        read_until(admin, is_state("IDLE"))
        controller.drop_next = True                          # e.g. PP to Main on the pendant
        lost = read_until(admin, is_state("DISCONNECTED"), timeout=15)
        assert lost["admin"]["home_confirmed"] is False
        # The monitor reconnects on its own and configures tool and work object again.
        back = read_until(admin, lambda m: m.get("type") == "state" and m["robot"]["connected"], timeout=15)
        assert back["state"] == "DISCONNECTED"               # an admin has to confirm home first
        before = len([c for c in controller.commands if c.startswith("07")])
        assert before >= 2
        assert command(client, "home")[0] == 200
        read_until(admin, is_state("IDLE"))


def test_remote_visitors_cannot_steer(stack, monkeypatch):
    client, _, engine = stack
    monkeypatch.setattr(engine.config.server, "visitor_control_hosts", ["127.0.0.1"])
    assert command(client, "home")[0] == 200
    with client.websocket_connect("/ws/visitor") as ws:
        assert ws.receive_json() == {"type": "hello", "control": False}
        read_until(ws, is_state("IDLE"))
        ws.send_json({"type": "start", "name": "Hacker", "birth_year": 2000})
        time.sleep(0.5)
    assert engine.sm.state.value == "IDLE" and engine.run is None
