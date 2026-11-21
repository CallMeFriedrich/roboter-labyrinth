"""State machine transitions, leaderboard and settings (CLAUDE.md §12)."""
from __future__ import annotations

from datetime import date

import pytest

from app.db import Database
from app.game.leaderboard import EntryError, Leaderboard, clean_birth_year, clean_name
from app.game.state_machine import ABORTABLE, TRANSITIONS, IllegalTransition, State, StateMachine
from app.game.timer import RunTimer, format_time
from app.geometry.lines import GateLine
from app.robot.jog_loop import KeyState, direction
from app.settings import Config, SettingsStore, hash_pin

S = State


# ------------------------------------------------------------- state machine
def walk(*states: State) -> StateMachine:
    sm = StateMachine()
    for state in states:
        sm.to(state)
    return sm


def test_visitor_run_path():
    sm = walk(S.IDLE, S.MOVING_TO_START, S.COUNTDOWN, S.ARMED, S.RUNNING, S.FINISHED,
              S.RETURNING_HOME, S.IDLE)
    assert sm.state == S.IDLE


def test_auto_run_paths():
    walk(S.IDLE, S.AUTO_REQUESTED, S.AUTO_RUN, S.RETURNING_HOME, S.IDLE)
    walk(S.IDLE, S.AUTO_REQUESTED, S.IDLE)            # rejected or timed out
    walk(S.IDLE, S.AUTO_RUN, S.RETURNING_HOME, S.IDLE)  # admin starts directly


def test_countdown_can_be_skipped():
    walk(S.IDLE, S.MOVING_TO_START, S.ARMED)


@pytest.mark.parametrize("state", sorted(ABORTABLE, key=lambda s: s.value))
def test_abort_from_every_abortable_state(state):
    sm = StateMachine()
    sm.state = state
    sm.to(S.ABORTING)
    sm.to(S.RETURNING_HOME)
    sm.to(S.IDLE)


@pytest.mark.parametrize("state", list(State))
def test_every_state_can_fail(state):
    sm = StateMachine()
    sm.state = state
    if state != S.ERROR:
        sm.to(S.ERROR)
    sm.to(S.DISCONNECTED)
    assert sm.state == S.DISCONNECTED


def test_illegal_transitions_are_refused():
    for origin, target in [(S.DISCONNECTED, S.RUNNING), (S.IDLE, S.RUNNING), (S.ARMED, S.FINISHED),
                           (S.RUNNING, S.IDLE), (S.FINISHED, S.ABORTING), (S.RETURNING_HOME, S.ABORTING),
                           (S.ERROR, S.IDLE), (S.AUTO_RUN, S.FINISHED)]:
        sm = StateMachine()
        sm.state = origin
        with pytest.raises(IllegalTransition):
            sm.to(target)
        assert sm.state == origin


def test_table_is_complete_and_listener_fires():
    assert set(TRANSITIONS) == set(State)
    seen = []
    sm = StateMachine(lambda old, new: seen.append((old, new)))
    sm.to(S.IDLE)
    sm.to(S.IDLE)                                      # no change, no event
    assert seen == [(S.DISCONNECTED, S.IDLE)]


# --------------------------------------------------------------------- timer
def test_timer_interpolates_gate_crossings():
    start = GateLine((10, -5), (10, 5), (1, 0))
    finish = GateLine((50, -5), (50, 5), (1, 0))
    timer = RunTimer(start, finish)
    assert timer.feed((0, 0), (8, 0), 0, 100_000_000) is None
    assert timer.feed((8, 0), (12, 0), 100_000_000, 200_000_000) == "started"
    assert timer.started_ns == 150_000_000 and timer.running
    assert timer.feed((12, 0), (8, 0), 200_000_000, 300_000_000) is None       # back over the start
    assert timer.feed((60, 0), (40, 0), 300_000_000, 400_000_000) is None      # finish backwards
    assert timer.feed((48, 0), (52, 0), 1_000_000_000, 1_100_000_000) == "finished"
    assert timer.time_ms == 900
    assert timer.feed((48, 0), (52, 0), 2_000_000_000, 2_100_000_000) is None  # only once


def test_finish_before_start_does_not_count():
    timer = RunTimer(GateLine((10, -5), (10, 5), (1, 0)), GateLine((50, -5), (50, 5), (1, 0)))
    assert timer.feed((48, 0), (52, 0), 0, 1) is None
    assert timer.started_ns is None and timer.time_ms is None and timer.elapsed_ms() == 0


def test_time_format():
    assert format_time(42170) == "0:42.17"
    assert format_time(0) == "0:00.00"
    assert format_time(61_005) == "1:01.00"
    assert format_time(599_999) == "9:59.99"


# ---------------------------------------------------------------------- keys
def test_direction_is_normalised():
    assert direction({"d"}) == (1.0, 0.0)
    assert direction({"w"}) == (0.0, -1.0)             # W = up = smaller y
    assert direction({"s", "a"}) == pytest.approx((-0.7071, 0.7071), abs=1e-4)
    assert direction({"a", "d"}) == (0.0, 0.0)
    assert direction({"w", "a", "s", "d"}) == (0.0, 0.0)
    assert direction(set()) == (0.0, 0.0)


def test_dead_man_releases_keys_after_300_ms():
    now = [0.0]
    keys = KeyState(clock=lambda: now[0])
    keys.update(["w", "d", "x", 5])
    assert keys.active() == {"w", "d"}                 # unknown keys are ignored
    now[0] = 0.29
    assert keys.active() == {"w", "d"}
    now[0] = 0.31
    assert keys.active() == frozenset()
    keys.update(["a"])
    now[0] = 0.5
    assert keys.active() == {"a"}                      # heartbeat keeps it alive
    keys.clear()
    assert keys.active() == frozenset()


# --------------------------------------------------------------- leaderboard
def test_name_and_year_validation():
    assert clean_name("  Lena   Maria ") == "Lena Maria"
    assert clean_name("A\x00n​na\n") == "Anna"
    assert clean_name("x" * 20) == "x" * 20
    for bad in ("", "   ", "\t\n", "x" * 21, None, 5):
        with pytest.raises(EntryError):
            clean_name(bad)
    today = date(2026, 11, 28)
    assert clean_birth_year("2009", today) == 2009
    assert clean_birth_year(1920, today) == 1920 and clean_birth_year(2026, today) == 2026
    for bad in (1919, 2027, "abc", "", None, 2009.5, True):
        with pytest.raises(EntryError):
            clean_birth_year(bad, today)


def test_sorting_placement_and_deleted_entries():
    db = Database(":memory:")
    lab = db.add_labyrinth("A", "<svg/>")
    other = db.add_labyrinth("B", "<svg/>")
    board = Leaderboard(db)
    assert board.top(lab) == [] and board.top(None) == []

    times = [50_000, 30_000, 40_000, 30_000] + [60_000 + i for i in range(10)]
    results = [board.add_finished(lab, f"P{i}", 2000 + i, t) for i, t in enumerate(times)]
    board.add_aborted(lab, "Quit", 2001)
    board.add_finished(other, "Elsewhere", 2001, 1)

    top = board.top(lab)
    assert len(top) == 10
    assert [e["time_ms"] for e in top[:4]] == [30_000, 30_000, 40_000, 50_000]
    assert [e["name"] for e in top[:2]] == ["P1", "P3"]          # tie: the earlier run is ahead
    assert [e["rank"] for e in top] == list(range(1, 11))
    assert results[0] == {"run_id": results[0]["run_id"], "name": "P0", "birth_year": 2000,
                          "time_ms": 50_000, "rank": 1, "total": 1, "new_best": True}
    assert (results[1]["rank"], results[1]["new_best"]) == (1, True)
    assert (results[3]["rank"], results[3]["total"], results[3]["new_best"]) == (2, 4, False)
    assert (results[-1]["rank"], results[-1]["total"]) == (14, 14)   # "Platz 14 von 14"

    db.delete_run(top[0]["run_id"])
    assert [e["name"] for e in board.top(lab)[:2]] == ["P3", "P2"]
    assert db.placement(lab, top[0]["run_id"]) is None
    assert db.placement(lab, results[-1]["run_id"]) == (13, 13)
    assert len(db.list_runs(lab)) == 14 and len(db.list_runs(lab, "Quit")) == 1

    db.reset_runs(lab)
    assert board.top(lab) == [] and len(board.top(other)) == 1


def test_robot_best_time_stays():
    db = Database(":memory:")
    lab = db.add_labyrinth("A", "<svg/>")
    board = Leaderboard(db)
    assert board.robot_best(lab) is None
    for t in (18_420, 17_900, 19_000):
        db.add_robot_run(lab, t, 250, "fine")
    assert board.robot_best(lab) == 17_900
    db.reset_robot_runs(lab)
    assert board.robot_best(lab) is None


# ------------------------------------------------------------------ settings
def test_settings_defaults_limits_and_persistence():
    db = Database(":memory:")
    config = Config()
    store = SettingsStore(db, config)
    assert store["visitor_speed"] == 50 and store["driver"] == "sim" and store["jog_zone"] == "z1"
    assert store.set("visitor_speed", 80) == 80.0
    assert store.set("countdown_s", 2.0) == 2 and isinstance(store["countdown_s"], int)
    for key, value in [("visitor_speed", 151), ("visitor_speed", 9), ("auto_speed", 1001),
                       ("wall_tolerance", 3.5), ("jog_zone", "z10"), ("driver", "egm"),
                       ("visitor_speed", "fast"), ("visitor_speed", True), ("unknown", 1)]:
        with pytest.raises(ValueError):
            store.set(key, value)
    with pytest.raises(ValueError):
        store.patch({"auto_speed": 300, "pin_diameter": 99})
    assert store["auto_speed"] == 250                  # nothing applied if one value is invalid
    assert SettingsStore(db, config)["visitor_speed"] == 80.0


def test_config_limits_tighten_the_built_in_limits():
    config = Config()
    config.limits = {"visitor_speed": (20.0, 60.0), "auto_speed": (10.0, 5000.0)}
    store = SettingsStore(Database(":memory:"), config)
    assert store.limits("visitor_speed") == (20.0, 60.0)
    assert store.limits("auto_speed") == (50.0, 1000.0)    # config can never widen them
    with pytest.raises(ValueError):
        store.set("visitor_speed", 80)


def test_pin_hash_is_salted_and_stable():
    assert hash_pin("1234") == hash_pin("1234") != hash_pin("1235")
    assert len(hash_pin("1234")) == 64
