"""WebSocket of the visitor screen (CLAUDE.md §8.12)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..game.engine import GameEngine, GameError
from ..game.leaderboard import EntryError

router = APIRouter()
log = logging.getLogger("api")

NOT_NOW = "Das geht gerade nicht. Bitte wende dich an einen Betreuer."


@router.websocket("/ws/visitor")
async def visitor_ws(ws: WebSocket) -> None:
    engine: GameEngine = ws.app.state.engine
    hub = ws.app.state.hub
    host = ws.client.host if ws.client else ""
    # Only the kiosk itself may steer; other devices in the hotspot just watch.
    control = host in engine.config.server.visitor_control_hosts
    await ws.accept()
    hub.visitors.add(ws)
    try:
        await ws.send_json({"type": "hello", "control": control})
        await ws.send_json(engine.snapshot())
        while True:
            message = await ws.receive_json()
            if not control or not isinstance(message, dict):
                continue
            kind = message.get("type")
            try:
                if kind == "keys":
                    down = message.get("down", [])
                    engine.set_keys(down if isinstance(down, list) else [])
                elif kind == "start":
                    await engine.start_run(message.get("name"), message.get("birth_year"))
                elif kind == "give_up":
                    await engine.give_up()
                elif kind == "speed":
                    engine.set_speed_mode(message.get("mode"))
                elif kind == "touch":
                    engine.touch()          # somebody types at the kiosk: no idle show now
                elif kind == "request_auto":
                    await engine.request_auto()
                elif kind == "cancel_auto":
                    await engine.reject_auto()
            except GameError as exc:
                # Visitors only see friendly texts, never technical reasons.
                text = str(exc) if isinstance(exc.__cause__, EntryError) else NOT_NOW
                await ws.send_json({"type": "error", "message": text})
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Fehler in der Besucher-Verbindung")
    finally:
        hub.visitors.discard(ws)
        if control:
            engine.keys.clear()     # dead man: a lost client releases all keys
