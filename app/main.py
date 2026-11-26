"""FastAPI application: routes, static files, lifespan.

Start:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import shutdown_guard
from .api import admin_rest, ws_admin, ws_visitor
from .api.hub import Auth, Hub
from .db import Database
from .game.engine import GameEngine
from .settings import ROOT, Config, load_config

WEB = ROOT / "web"


def _setup_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_labyrinth_configured", False):
        return
    root._labyrinth_configured = True      # type: ignore[attr-defined]
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    log_dir = ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    file = RotatingFileHandler(log_dir / "server.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    file.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.setLevel(logging.INFO)
    root.addHandler(console)
    root.addHandler(file)


class NoCacheStatic(StaticFiles):
    """The UI files change while tuning; never let a kiosk browser serve stale ones."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if not path.startswith("fonts/"):
            response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(config: Config | None = None, db: Database | None = None, seed: bool = True) -> FastAPI:
    config = config or load_config()
    if db is None:
        _setup_logging()
        db = Database(config.resolve(config.paths.database))
    hub = Hub()
    engine = GameEngine(config, db, hub, seed=seed)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await engine.start()
        shutdown_guard.install()          # Ctrl+C always ends the server, even if a connection hangs
        try:
            yield
        finally:
            try:
                await asyncio.wait_for(engine.stop(), timeout=4)
            except asyncio.TimeoutError:
                logging.getLogger("server").warning("Roboter/Spiel haben nicht rechtzeitig gestoppt.")
            shutdown_guard.disarm()

    app = FastAPI(title="Roboter-Labyrinth", lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.state.engine, app.state.hub, app.state.auth = engine, hub, Auth(config)
    app.include_router(admin_rest.router)
    app.include_router(ws_visitor.router)
    app.include_router(ws_admin.router)

    @app.get("/")
    async def visitor_page() -> FileResponse:
        return FileResponse(WEB / "visitor" / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/stats")
    async def stats_page() -> FileResponse:
        return FileResponse(WEB / "stats" / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/admin")
    async def admin_page() -> FileResponse:
        return FileResponse(WEB / "admin" / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", NoCacheStatic(directory=WEB), name="static")
    return app


_app: FastAPI | None = None


def __getattr__(name: str):
    # Lazy `app` attribute: importing this module (tests) must not open the real database.
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
