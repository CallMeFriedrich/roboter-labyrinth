"""Shared fixtures: the first labyrinth draft and a small straight test labyrinth."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from shapely.geometry import Point, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import Database  # noqa: E402
from app.geometry.svg_import import parse_svg  # noqa: E402
from app.settings import Config  # noqa: E402

DRAFT = ROOT / "tests" / "data" / "Labyrinth_Deckplatte_Entwurf1.svg"

SVG_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="400mm" height="400mm" viewBox="0 0 400 400">
  <g id="Gravur_Logo"><path fill="#000000" d="M 300,300 L 340,300 L 340,320 L 300,320 Z"/></g>
  <g id="Schnitt">
    <path fill="none" stroke="#FF0000" stroke-width="0.1" d="{channel}"/>
    <path fill="none" stroke="#FF0000" stroke-width="0.1" d="{bores}"/>
    <path fill="none" stroke="#FF0000" stroke-width="0.1" d="M 0,0 L 400,0 L 400,400 L 0,400 Z"/>
  </g>
</svg>"""


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="session")
def draft_svg() -> str:
    return DRAFT.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def draft(draft_svg):
    return parse_svg(draft_svg)


def make_simple_svg(holes: int = 4, corridor: float = 16.0) -> str:
    """Straight corridor from a Ø 26 circle at (60|200) to one at (200|200)."""
    half = corridor / 2
    shape = unary_union([Point(60, 200).buffer(13, quad_segs=24), box(60, 200 - half, 200, 200 + half),
                         Point(200, 200).buffer(13, quad_segs=24)])
    channel = "M " + " L ".join(f"{x:.3f},{y:.3f}" for x, y in list(shape.exterior.coords)[:-1]) + " Z"
    centres = [(7.5, 7.5), (392.5, 7.5), (7.5, 392.5), (392.5, 392.5)][:holes]
    bores = " ".join(f"M {x - 2.5},{y} A 2.5,2.5 0 1 0 {x + 2.5},{y} A 2.5,2.5 0 1 0 {x - 2.5},{y} Z"
                     for x, y in centres)
    return SVG_TEMPLATE.format(channel=channel, bores=bores)


@pytest.fixture(scope="session")
def simple_svg() -> str:
    return make_simple_svg()


def fast_config(**robot) -> Config:
    """Simulator that runs 8 times faster than real time."""
    config = Config()
    config.sim.time_scale = 8.0
    config.sim.latency_ms = 1.0
    config.server.visitor_control_hosts = ["testclient", "127.0.0.1"]
    config.admin.pin_sha256 = ""
    for key, value in robot.items():
        setattr(config.robot, key, value)
    return config


def simple_db(svg: str) -> Database:
    """In-memory database with the simple labyrinth as the only one."""
    db = Database(":memory:")
    db.set_setting("countdown_s", 0)
    db.set_setting("result_display_s", 3)
    db.set_setting("visitor_speed", 150.0)
    db.set_setting("auto_speed", 1000.0)
    db.add_labyrinth("Test", svg)
    return db
