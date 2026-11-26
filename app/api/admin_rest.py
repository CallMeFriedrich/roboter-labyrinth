"""REST API of the admin panel (CLAUDE.md §8.12)."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from ..game.engine import GameEngine, GameError
from .hub import SESSION_COOKIE, AuthError

router = APIRouter(prefix="/api")


def _engine(request: Request) -> GameEngine:
    return request.app.state.engine


def require_admin(request: Request) -> None:
    if not request.app.state.auth.valid(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(status_code=401, detail="Bitte zuerst anmelden.")


def _point(raw: Any) -> tuple[float, float]:
    x, y = raw
    return float(x), float(y)


# ------------------------------------------------------------------- session
@router.post("/admin/login")
async def login(request: Request) -> JSONResponse:
    auth = request.app.state.auth
    try:
        body = await request.json()
        token = auth.login(str(body.get("pin", "")))
    except AuthError as exc:
        return JSONResponse({"message": str(exc)}, status_code=401)
    except Exception:
        return JSONResponse({"message": "Ungültige Anfrage."}, status_code=400)
    response = JSONResponse({"ok": True})
    response.set_cookie(SESSION_COOKIE, token, max_age=auth.max_age, httponly=True, samesite="strict")
    return response


@router.post("/admin/logout")
async def logout(request: Request) -> JSONResponse:
    request.app.state.auth.logout(request.cookies.get(SESSION_COOKIE))
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("/admin/session")
async def session(request: Request) -> dict:
    return {"ok": request.app.state.auth.valid(request.cookies.get(SESSION_COOKIE))}


# --------------------------------------------------------------------- reads
@router.get("/admin/state", dependencies=[Depends(require_admin)])
async def state(request: Request) -> dict:
    engine = _engine(request)
    return {"state": engine.admin_snapshot(), "definitions": engine.settings.describe(),
            "limits": {"admin_jog_speed": engine.config.robot.admin_jog_speed}}


@router.get("/admin/labyrinths", dependencies=[Depends(require_admin)])
async def labyrinths(request: Request) -> list[dict]:
    return _engine(request).db.list_labyrinths()


@router.get("/admin/labyrinths/{labyrinth_id}", dependencies=[Depends(require_admin)])
async def labyrinth(labyrinth_id: int, request: Request) -> Any:
    try:
        return _engine(request).labyrinth_detail(labyrinth_id)
    except GameError as exc:
        return JSONResponse({"message": str(exc)}, status_code=404)


@router.get("/admin/runs", dependencies=[Depends(require_admin)])
async def runs(request: Request, search: str = "") -> list[dict]:
    engine = _engine(request)
    if engine.lab is None:
        return []
    return engine.db.list_runs(engine.lab.id, search.strip()[:40])


@router.get("/logo")
async def logo(request: Request) -> dict:
    """Engraving of the active labyrinth (TFO logo) for the visitor screen."""
    engine = _engine(request)
    if engine.lab is None or not engine.lab.geometry.engraving:
        return {"paths": [], "bounds": None}
    geometry = engine.lab.geometry
    paths = geometry.logo or geometry.engraving
    box = geometry.logo_bounds if geometry.logo else geometry.engraving_bounds
    return {"paths": paths, "bounds": [float(v) for v in box] if box else None}


# ------------------------------------------------------------------ commands
Handler = Callable[[GameEngine, dict], Awaitable[Any]]


async def _sync(result: Any) -> Any:
    return result


COMMANDS: dict[str, Handler] = {
    "connect": lambda e, b: e.connect(),
    "disconnect": lambda e, b: e.disconnect(),
    "home": lambda e, b: e.go_home(),
    "start_pose": lambda e, b: e.go_start_pose(),
    "teach_home": lambda e, b: e.teach_home(),
    "set_frame": lambda e, b: e.set_frame(str(b["mode"])),
    "jog_step": lambda e, b: e.jog_step(str(b["frame"]), b["dir"], float(b["step"])),
    "goto": lambda e, b: e.move_to(str(b["frame"]), b["xyz"]),
    "set_tool": lambda e, b: e.set_tool(b["values"]),
    "settings": lambda e, b: e.patch_settings(b["values"]),
    "calib_point": lambda e, b: e.calib_save_point(int(b["index"])),
    "calib_clear": lambda e, b: _sync(e.calib_clear()),
    "calib_activate": lambda e, b: e.calib_activate(),
    "calib_remove": lambda e, b: e.calib_remove(),
    "sim_hole": lambda e, b: e.sim_goto_hole(int(b["index"])),
    "calib_goto": lambda e, b: e.calib_goto_hole(int(b["index"]), float(b.get("clearance", 20.0))),
    "lab_upload": lambda e, b: _sync({"id": e.upload_labyrinth(str(b.get("name", "")), str(b["svg"]))}),
    "lab_point": lambda e, b: _sync(e.set_point(int(b["id"]), str(b["which"]), _point(b["p"]))),
    "lab_gate": lambda e, b: _sync(e.set_gate(int(b["id"]), str(b["which"]), _point(b["p"]), _point(b["q"]))),
    "lab_flip": lambda e, b: _sync(e.flip_gate(int(b["id"]), str(b["which"]))),
    "lab_swap": lambda e, b: _sync(e.swap_start_finish(int(b["id"]))),
    "lab_path": lambda e, b: _sync(e.compute_path(int(b["id"]))),
    "lab_activate": lambda e, b: _sync(e.activate_labyrinth(int(b["id"]))),
    "lab_delete": lambda e, b: _sync(e.delete_labyrinth(int(b["id"]))),
    "auto_start": lambda e, b: e.start_auto(),
    "auto_reject": lambda e, b: e.reject_auto(),
    "abort": lambda e, b: e.abort(),
    "release": lambda e, b: _sync(e.release()),
    "pause": lambda e, b: _sync(e.pause()),
    "run_delete": lambda e, b: _sync(e.delete_run(int(b["id"]))),
    "board_reset": lambda e, b: _sync(e.reset_leaderboard()),
    "robot_best_reset": lambda e, b: _sync(e.reset_robot_best()),
}


@router.post("/admin/cmd/{name}", dependencies=[Depends(require_admin)])
async def command(name: str, request: Request) -> JSONResponse:
    handler = COMMANDS.get(name)
    if handler is None:
        return JSONResponse({"message": "Unbekannter Befehl."}, status_code=404)
    try:
        raw = await request.body()
        body = await request.json() if raw else {}
        if not isinstance(body, dict):
            raise TypeError
        result = await handler(_engine(request), body)
    except GameError as exc:
        return JSONResponse({"message": str(exc)}, status_code=400)
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"message": "Ungültige Anfrage."}, status_code=400)
    _engine(request).notify()
    return JSONResponse({"ok": True, "result": result})
