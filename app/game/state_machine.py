"""Game states and the allowed transitions (CLAUDE.md §8.8)."""
from __future__ import annotations

from enum import Enum
from typing import Callable


class State(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    IDLE = "IDLE"
    MOVING_TO_START = "MOVING_TO_START"
    COUNTDOWN = "COUNTDOWN"
    ARMED = "ARMED"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    RETURNING_HOME = "RETURNING_HOME"
    ABORTING = "ABORTING"
    AUTO_REQUESTED = "AUTO_REQUESTED"
    AUTO_RUN = "AUTO_RUN"
    ERROR = "ERROR"


S = State

TRANSITIONS: dict[State, frozenset[State]] = {
    S.DISCONNECTED: frozenset({S.IDLE, S.ERROR}),
    S.IDLE: frozenset({S.MOVING_TO_START, S.AUTO_REQUESTED, S.AUTO_RUN, S.DISCONNECTED, S.ERROR}),
    S.MOVING_TO_START: frozenset({S.COUNTDOWN, S.ARMED, S.ABORTING, S.ERROR}),
    S.COUNTDOWN: frozenset({S.ARMED, S.ABORTING, S.ERROR}),
    S.ARMED: frozenset({S.RUNNING, S.ABORTING, S.ERROR}),
    S.RUNNING: frozenset({S.FINISHED, S.ABORTING, S.ERROR}),
    S.FINISHED: frozenset({S.RETURNING_HOME, S.ERROR}),
    S.RETURNING_HOME: frozenset({S.IDLE, S.ERROR}),
    S.ABORTING: frozenset({S.RETURNING_HOME, S.ERROR}),
    S.AUTO_REQUESTED: frozenset({S.AUTO_RUN, S.IDLE, S.DISCONNECTED, S.ERROR}),
    S.AUTO_RUN: frozenset({S.RETURNING_HOME, S.ABORTING, S.ERROR}),
    S.ERROR: frozenset({S.DISCONNECTED}),
}

# States in which "Aufgeben" / "Lauf abbrechen" does something.
ABORTABLE = frozenset({S.MOVING_TO_START, S.COUNTDOWN, S.ARMED, S.RUNNING, S.AUTO_RUN})
# States in which the visitor may steer with W A S D.
JOG_STATES = frozenset({S.ARMED, S.RUNNING})
# States in which a run (visitor or robot) occupies the exhibit.
BUSY_STATES = frozenset(State) - {S.DISCONNECTED, S.IDLE, S.AUTO_REQUESTED, S.ERROR}


class IllegalTransition(Exception):
    pass


class StateMachine:
    def __init__(self, on_change: Callable[[State, State], None] | None = None):
        self.state = State.DISCONNECTED
        self._on_change = on_change

    def can(self, new: State) -> bool:
        return new in TRANSITIONS[self.state]

    def to(self, new: State) -> None:
        if new == self.state:
            return
        if not self.can(new):
            raise IllegalTransition(f"{self.state.value} → {new.value} ist nicht erlaubt")
        old, self.state = self.state, new
        if self._on_change is not None:
            self._on_change(old, new)
