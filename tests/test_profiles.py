"""Leaderboard profiles, CSV export, statistics data and the visitor look."""
from __future__ import annotations

import csv
import io
import sqlite3
from datetime import date

import pytest

from app.db import Database
from app.game.engine import GameError
from app.game.export import file_name, runs_csv
from app.game.leaderboard import Leaderboard

from .conftest import run
from .test_game import make_engine


def test_runs_belong_to_the_active_profile():
    db = Database(":memory:")
    board = Leaderboard(db)
    assert [p["name"] for p in db.profiles()] == ["Standard"]
    board.add_finished(1, "Probe", 2010, 30_000)
    rehearsal = db.active_profile()["id"]

    day = db.add_profile("Tag der offenen Tür")
    db.activate_profile(day)
    assert board.top(1) == []                                   # new profile: empty board
    result = board.add_finished(1, "Lena", 2011, 40_000)
    assert (result["rank"], result["total"]) == (1, 1)           # the rehearsal time does not count
    assert [r["name"] for r in db.list_runs(1)] == ["Lena"]

    db.reset_runs(1)                                             # resets only the active profile
    db.activate_profile(rehearsal)
    assert [e["name"] for e in board.top(1)] == ["Probe"]
    counts = {p["name"]: p["runs"] for p in db.profiles()}
    assert counts == {"Standard": 1, "Tag der offenen Tür": 0}

    db.delete_profile(day)
    assert [p["name"] for p in db.profiles()] == ["Standard"]
    db.delete_profile(rehearsal)                                 # the active one is never deleted
    assert [p["name"] for p in db.profiles()] == ["Standard"]


def test_old_runs_move_into_the_standard_profile(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE runs(id INTEGER PRIMARY KEY, labyrinth_id INTEGER, name TEXT, birth_year INTEGER,
            time_ms INTEGER, status TEXT, created_at TEXT, deleted INTEGER DEFAULT 0,
            speed_mode TEXT DEFAULT 'normal');
        INSERT INTO runs(labyrinth_id, name, birth_year, time_ms, status, created_at)
            VALUES(1, 'Alt', 2008, 40000, 'finished', '2026-11-20');
    """)
    conn.commit()
    conn.close()
    db = Database(path)
    assert db.active_profile()["name"] == "Standard"
    assert [e["name"] for e in Leaderboard(db).top(1)] == ["Alt"]
    db.close()


def test_csv_export_opens_in_excel_with_places_per_speed():
    runs = [
        {"id": 1, "labyrinth_id": 1, "labyrinth": "Heißer Draht", "name": "Lena", "birth_year": 2011,
         "time_ms": 41_230, "status": "finished", "speed_mode": "normal", "created_at": "2026-11-28T10:00:00"},
        {"id": 2, "labyrinth_id": 1, "labyrinth": "Heißer Draht", "name": "Max", "birth_year": 2010,
         "time_ms": 38_870, "status": "finished", "speed_mode": "normal", "created_at": "2026-11-28T10:05:00"},
        {"id": 3, "labyrinth_id": 1, "labyrinth": "Heißer Draht", "name": "Jörg", "birth_year": 1980,
         "time_ms": 21_450, "status": "finished", "speed_mode": "turbo", "created_at": "2026-11-28T10:07:00"},
        {"id": 4, "labyrinth_id": 1, "labyrinth": "Heißer Draht", "name": "Mia", "birth_year": 2012,
         "time_ms": None, "status": "aborted", "speed_mode": "normal", "created_at": "2026-11-28T10:09:00"},
    ]
    text = runs_csv(runs, today=date(2026, 11, 28))
    assert text.startswith("﻿")
    rows = list(csv.reader(io.StringIO(text[1:]), delimiter=";"))
    assert rows[0][:3] == ["Platz im Tempo", "Tempo", "Name"]
    body = [r[:7] + [r[7]] for r in rows[1:]]
    assert body[0][:7] == ["1", "Normal", "Max", "2010", "16", "0:38.87", "38870"]
    assert body[1][:3] == ["2", "Normal", "Lena"]
    assert body[2][:3] == ["", "Normal", "Mia"] and body[2][7] == "abgebrochen"
    assert body[3][:3] == ["1", "Turbo", "Jörg"]
    assert file_name("Tag der offenen Tür", date(2026, 11, 28)) == "Bestenliste_Tag_der_offenen_Tür_2026-11-28.csv"


def test_engine_profiles_stats_and_display(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            snap = engine.snapshot()
            assert snap["display"] == {"theme": "dark", "rotate_s": 8}
            assert snap["profile"]["name"] == "Standard"
            await engine.patch_settings({"visitor_theme": "light", "board_rotate_s": 0})
            assert engine.snapshot()["display"] == {"theme": "light", "rotate_s": 0}
            with pytest.raises(GameError):
                await engine.patch_settings({"visitor_theme": "bunt"})

            with pytest.raises(GameError):
                engine.create_profile("   ")
            day = engine.create_profile("Tag der offenen Tür", activate=True)
            assert engine.snapshot()["profile"] == {"id": day, "name": "Tag der offenen Tür"}
            with pytest.raises(GameError):
                engine.delete_profile(day)                       # active
            rev = engine.snapshot()["runs_rev"]
            engine.board.add_finished(engine.lab.id, "Lena", 2011, 40_000, "turbo")
            assert engine.snapshot()["runs_rev"] != rev

            stats = engine.stats()
            assert stats["profile"]["name"] == "Tag der offenen Tür"
            first = stats["runs"][0]
            assert stats["runs"] == [{"id": first["id"], "name": "Lena", "birth_year": 2011, "time_ms": 40_000,
                                      "status": "finished", "mode": "turbo", "at": first["at"], "replay": False}]
            assert [e["name"] for e in stats["boards"]["turbo"]] == ["Lena"]
            assert "profiles" in engine.admin_snapshot()["admin"]

            await engine.start_run("Max", 2010)
            with pytest.raises(GameError):
                engine.activate_profile(1)                       # not during a run
            await engine.abort()
        finally:
            await engine.stop()
    run(scenario())
