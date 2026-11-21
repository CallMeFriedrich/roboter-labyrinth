"""WebSocket of the admin panel: live state, hold-to-move jog, fast abort."""
from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..game.engine import GameEngine, GameError
from .hub import SESSION_COOKIE

router = APIRouter()
log = logging.getLogger("api")


@router.websocket("/ws/admin")
async def admin_ws(ws: WebSocket) -> None:
    engine: GameEngine = ws.app.state.engine
    hub = ws.app.state.hub
    await ws.accept()
    if not ws.app.state.auth.valid(ws.cookies.get(SESSION_COOKIE)):
        # Accept first: only then the browser sees the close code and shows the login.
        await ws.close(code=4401)
        return
    hub.admins.add(ws)
    try:
        await ws.send_json(engine.admin_snapshot())
        while True:
            message = await ws.receive_json()
            if not isinstance(message, dict):
                continue
            kind = message.get("type")
            try:
                if kind == "jog_hold":
                    await engine.jog_hold(str(message.get("frame")), message.get("dir", [0, 0, 0]))
                elif kind == "abort":
                    await engine.abort()
            except GameError as exc:
                await ws.send_json({"type": "error", "message": str(exc)})
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Fehler in der Admin-Verbindung")
    finally:
        hub.admins.discard(ws)
        engine._hold = None         # a lost tablet stops hold-to-move at once
