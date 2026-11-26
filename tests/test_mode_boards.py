"""Every speed mode (Langsam / Normal / Turbo) has its own leaderboard."""
from __future__ import annotations

import sqlite3

from app.db import Database
from app.game.leaderboard import Leaderboard
from app.game.state_machine import State

from .conftest import run
from .test_game import hold, make_engine, wait_for

S = State


def test_each_speed_has_its_own_board_and_placement():
    db = Database(":memory:")
    board = Leaderboard(db)
    board.add_finished(1, "Turbo-Tom", 2009, 9_000, "turbo")
    board.add_finished(1, "Lena", 2010, 30_000, "normal")
    board.add_finished(1, "Max", 2011, 25_000, "normal")
    snail = board.add_finished(1, "Schnecke", 2012, 60_000, "slow")
    board.add_aborted(1, "Weg", 2010, "turbo")

    boards = board.boards(1)
    assert [e["name"] for e in boards["normal"]] == ["Max", "Lena"]
    assert [e["name"] for e in boards["turbo"]] == ["Turbo-Tom"]
    assert [e["name"] for e in boards["slow"]] == ["Schnecke"]
    # The slow run is not beaten by the much faster turbo run: it is first among the slow ones.
    assert snail["rank"] == 1 and snail["total"] == 1 and snail["new_best"] and snail["speed_mode"] == "slow"
    lena_rank = db.placement(1, boards["normal"][1]["run_id"])
    assert lena_rank == (2, 2)
    assert {r["speed_mode"] for r in db.list_runs(1)} == {"slow", "normal", "turbo"}


def test_old_database_gets_the_speed_column(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE runs(id INTEGER PRIMARY KEY, labyrinth_id INTEGER, name TEXT, birth_year INTEGER,
            time_ms INTEGER, status TEXT CHECK(status IN ('finished','aborted')),
            created_at TEXT, deleted INTEGER DEFAULT 0);
        INSERT INTO runs(labyrinth_id, name, birth_year, time_ms, status, created_at)
            VALUES(1, 'Alt', 2008, 40000, 'finished', '2026-11-20');
    """)
    conn.commit()
    conn.close()
    db = Database(path)
    top = Leaderboard(db).top(1, "normal")
    assert [e["name"] for e in top] == ["Alt"]                     # old runs count as "Normal"
    db.close()


def test_snapshot_sends_all_boards_and_the_run_lands_on_its_own(simple_svg):
    async def scenario():
        engine = await make_engine(simple_svg)
        try:
            engine.set_speed_mode("turbo")
            await engine.start_run("Lena", 2009)
            await wait_for(engine, S.ARMED)
            await hold(engine, ["d"], lambda: engine.sm.state in (S.FINISHED, S.RETURNING_HOME, S.IDLE), timeout=30)
            snap = engine.snapshot()
            assert snap["result"]["speed_mode"] == "turbo"
            assert [e["name"] for e in snap["boards"]["turbo"]] == ["Lena"]
            assert snap["boards"]["normal"] == [] and snap["boards"]["slow"] == []
            assert snap["leaderboard"] == snap["boards"]["turbo"]   # the shown board follows the run
            await wait_for(engine, S.IDLE, timeout=30)
        finally:
            await engine.stop()
    run(scenario())
