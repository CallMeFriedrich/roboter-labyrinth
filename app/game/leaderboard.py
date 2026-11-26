"""Leaderboard: input validation, top 10 and placement (CLAUDE.md §8.10)."""
from __future__ import annotations

import unicodedata
from datetime import date

from ..db import Database

NAME_MAX = 20
YEAR_MIN = 1920
TOP_N = 10
SPEED_MODES = ("slow", "normal", "turbo")     # every speed mode has its own board


class EntryError(ValueError):
    """Invalid name or birth year; the message is shown to the visitor."""


def clean_name(raw: object) -> str:
    if not isinstance(raw, str):
        raise EntryError("Bitte gib deinen Namen ein.")
    # Remove control and formatting characters, collapse whitespace.
    text = "".join(ch for ch in raw if unicodedata.category(ch)[0] != "C")
    text = " ".join(text.split())
    if not text:
        raise EntryError("Bitte gib deinen Namen ein.")
    if len(text) > NAME_MAX:
        raise EntryError(f"Der Name darf höchstens {NAME_MAX} Zeichen haben.")
    return text


def clean_birth_year(raw: object, today: date | None = None) -> int:
    current = (today or date.today()).year
    try:
        if isinstance(raw, bool) or (isinstance(raw, float) and not raw.is_integer()):
            raise ValueError
        year = int(str(raw).strip()) if isinstance(raw, str) else int(raw)
    except (TypeError, ValueError):
        raise EntryError("Bitte gib ein Geburtsjahr wie 2009 ein.") from None
    if not (YEAR_MIN <= year <= current):
        raise EntryError("Bitte gib ein Geburtsjahr wie 2009 ein.")
    return year


class Leaderboard:
    def __init__(self, db: Database):
        self._db = db

    def top(self, labyrinth_id: int | None, speed_mode: str = "normal") -> list[dict]:
        if labyrinth_id is None:
            return []
        rows = self._db.top_runs(labyrinth_id, TOP_N, speed_mode)
        return [{"rank": i + 1, "run_id": r["id"], "name": r["name"], "birth_year": r["birth_year"],
                 "time_ms": r["time_ms"]} for i, r in enumerate(rows)]

    def boards(self, labyrinth_id: int | None) -> dict[str, list[dict]]:
        """Top 10 of every speed mode."""
        return {mode: self.top(labyrinth_id, mode) for mode in SPEED_MODES}

    def add_finished(self, labyrinth_id: int, name: str, birth_year: int, time_ms: int,
                     speed_mode: str = "normal") -> dict:
        run_id = self._db.add_run(labyrinth_id, name, birth_year, time_ms, "finished", speed_mode)
        rank, total = self._db.placement(labyrinth_id, run_id)
        return {"run_id": run_id, "name": name, "birth_year": birth_year, "time_ms": time_ms,
                "rank": rank, "total": total, "new_best": rank == 1, "speed_mode": speed_mode}

    def add_aborted(self, labyrinth_id: int, name: str, birth_year: int,
                    speed_mode: str = "normal") -> int:
        return self._db.add_run(labyrinth_id, name, birth_year, None, "aborted", speed_mode)

    def robot_best(self, labyrinth_id: int | None) -> int | None:
        return self._db.best_robot_ms(labyrinth_id) if labyrinth_id is not None else None
