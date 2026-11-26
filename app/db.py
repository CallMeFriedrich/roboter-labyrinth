"""SQLite schema and access (CLAUDE.md §8.10).

All calls are short and synchronous; they run directly on the event loop.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS labyrinths(
    id INTEGER PRIMARY KEY, name TEXT, svg TEXT, created_at TEXT, active INTEGER DEFAULT 0,
    start_line TEXT, finish_line TEXT, path TEXT);
CREATE TABLE IF NOT EXISTS runs(
    id INTEGER PRIMARY KEY, labyrinth_id INTEGER, name TEXT, birth_year INTEGER,
    time_ms INTEGER, status TEXT CHECK(status IN ('finished','aborted')),
    created_at TEXT, deleted INTEGER DEFAULT 0, speed_mode TEXT DEFAULT 'normal');
CREATE TABLE IF NOT EXISTS robot_runs(
    id INTEGER PRIMARY KEY, labyrinth_id INTEGER, time_ms INTEGER, speed REAL,
    timing_method TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS calibration(
    id INTEGER PRIMARY KEY, created_at TEXT, p1 TEXT, p2 TEXT, p3 TEXT, p4_check TEXT,
    wobj TEXT, tool TEXT, active INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS runs_board ON runs(labyrinth_id, status, deleted, time_ms);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _loads(text: str | None) -> Any:
    return json.loads(text) if text else None


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)
            # Older databases: runs had no speed mode yet -> those runs count as "normal".
            columns = {row[1] for row in self._conn.execute("PRAGMA table_info(runs)")}
            if "speed_mode" not in columns:
                self._conn.execute("ALTER TABLE runs ADD COLUMN speed_mode TEXT DEFAULT 'normal'")
                self._conn.execute("UPDATE runs SET speed_mode='normal' WHERE speed_mode IS NULL")

    def close(self) -> None:
        self._conn.close()

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock, self._conn:
            return self._conn.execute(sql, params)

    def _all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def backup(self, directory: str | Path) -> Path | None:
        """Copy the database file with a timestamp (CLAUDE.md §14)."""
        if self.path == ":memory:" or not Path(self.path).exists():
            return None
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"labyrinth_{datetime.now():%Y%m%d_%H%M%S}.db"
        with self._lock:
            self._conn.commit()
            shutil.copy2(self.path, target)
        backups = sorted(directory.glob("labyrinth_*.db"))
        for old in backups[:-30]:
            old.unlink(missing_ok=True)
        return target

    # ---------------------------------------------------------------- settings
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self._one("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self._exec("INSERT INTO settings(key, value) VALUES(?, ?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    # -------------------------------------------------------------- labyrinths
    @staticmethod
    def _labyrinth(row: sqlite3.Row | None, with_svg: bool = True) -> dict | None:
        if row is None:
            return None
        data = {"id": row["id"], "name": row["name"], "created_at": row["created_at"],
                "active": bool(row["active"]), "start_line": _loads(row["start_line"]),
                "finish_line": _loads(row["finish_line"]), "path": _loads(row["path"])}
        if with_svg:
            data["svg"] = row["svg"]
        return data

    def add_labyrinth(self, name: str, svg: str) -> int:
        return self._exec("INSERT INTO labyrinths(name, svg, created_at, active) VALUES(?,?,?,0)",
                          (name, svg, _now())).lastrowid

    def list_labyrinths(self) -> list[dict]:
        return [self._labyrinth(r, with_svg=False)
                for r in self._all("SELECT * FROM labyrinths ORDER BY id DESC")]

    def get_labyrinth(self, labyrinth_id: int) -> dict | None:
        return self._labyrinth(self._one("SELECT * FROM labyrinths WHERE id=?", (labyrinth_id,)))

    def get_active_labyrinth(self) -> dict | None:
        return self._labyrinth(self._one("SELECT * FROM labyrinths WHERE active=1 ORDER BY id DESC LIMIT 1"))

    def set_active_labyrinth(self, labyrinth_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE labyrinths SET active=0")
            self._conn.execute("UPDATE labyrinths SET active=1 WHERE id=?", (labyrinth_id,))

    def update_labyrinth(self, labyrinth_id: int, **fields: Any) -> None:
        allowed = {"name", "start_line", "finish_line", "path"}
        for key, value in fields.items():
            if key not in allowed:
                raise KeyError(key)
            stored = value if key == "name" else json.dumps(value)
            self._exec(f"UPDATE labyrinths SET {key}=? WHERE id=?", (stored, labyrinth_id))

    def delete_labyrinth(self, labyrinth_id: int) -> None:
        self._exec("DELETE FROM labyrinths WHERE id=? AND active=0", (labyrinth_id,))

    # -------------------------------------------------------------------- runs
    def add_run(self, labyrinth_id: int, name: str, birth_year: int, time_ms: int | None,
                status: str, speed_mode: str = "normal") -> int:
        return self._exec(
            "INSERT INTO runs(labyrinth_id, name, birth_year, time_ms, status, created_at, speed_mode) "
            "VALUES(?,?,?,?,?,?,?)",
            (labyrinth_id, name, birth_year, time_ms, status, _now(), speed_mode)).lastrowid

    def top_runs(self, labyrinth_id: int, limit: int = 10, speed_mode: str = "normal") -> list[dict]:
        """Best finished runs of one speed mode (every mode has its own board)."""
        rows = self._all(
            "SELECT id, name, birth_year, time_ms FROM runs WHERE labyrinth_id=? AND "
            "status='finished' AND deleted=0 AND speed_mode=? ORDER BY time_ms, id LIMIT ?",
            (labyrinth_id, speed_mode, limit))
        return [dict(r) for r in rows]

    def placement(self, labyrinth_id: int, run_id: int) -> tuple[int, int] | None:
        """(rank, total) of a finished run among the finished runs of the same speed mode."""
        run = self._one("SELECT time_ms, speed_mode FROM runs WHERE id=? AND status='finished' "
                        "AND deleted=0", (run_id,))
        if run is None:
            return None
        mode = run["speed_mode"]
        base = "FROM runs WHERE labyrinth_id=? AND status='finished' AND deleted=0 AND speed_mode=?"
        better = self._one(f"SELECT COUNT(*) AS n {base} AND (time_ms < ? OR (time_ms = ? AND id < ?))",
                           (labyrinth_id, mode, run["time_ms"], run["time_ms"], run_id))["n"]
        total = self._one(f"SELECT COUNT(*) AS n {base}", (labyrinth_id, mode))["n"]
        return better + 1, total

    def list_runs(self, labyrinth_id: int, search: str = "", limit: int = 500) -> list[dict]:
        rows = self._all(
            "SELECT id, name, birth_year, time_ms, status, created_at, speed_mode FROM runs "
            "WHERE labyrinth_id=? AND deleted=0 AND name LIKE ? ORDER BY id DESC LIMIT ?",
            (labyrinth_id, f"%{search}%", limit))
        return [dict(r) for r in rows]

    def delete_run(self, run_id: int) -> None:
        self._exec("UPDATE runs SET deleted=1 WHERE id=?", (run_id,))

    def reset_runs(self, labyrinth_id: int) -> None:
        self._exec("UPDATE runs SET deleted=1 WHERE labyrinth_id=?", (labyrinth_id,))

    # -------------------------------------------------------------- robot runs
    def add_robot_run(self, labyrinth_id: int, time_ms: int, speed: float, timing_method: str) -> int:
        return self._exec(
            "INSERT INTO robot_runs(labyrinth_id, time_ms, speed, timing_method, created_at) "
            "VALUES(?,?,?,?,?)", (labyrinth_id, time_ms, speed, timing_method, _now())).lastrowid

    def best_robot_ms(self, labyrinth_id: int) -> int | None:
        row = self._one("SELECT MIN(time_ms) AS best FROM robot_runs WHERE labyrinth_id=?", (labyrinth_id,))
        return row["best"] if row else None

    def reset_robot_runs(self, labyrinth_id: int) -> None:
        self._exec("DELETE FROM robot_runs WHERE labyrinth_id=?", (labyrinth_id,))

    # ------------------------------------------------------------- calibration
    def add_calibration(self, points: list[list[float] | None], wobj: list[float],
                        tool: list[float], active: bool = True, pen_quat: list[float] | None = None) -> int:
        # The pen orientation measured at the holes is kept next to the tool (same column).
        stored_tool = {"tool": tool, "pen_quat": pen_quat} if pen_quat is not None else tool
        with self._lock, self._conn:
            if active:
                self._conn.execute("UPDATE calibration SET active=0")
            padded = (list(points) + [None] * 4)[:4]
            cur = self._conn.execute(
                "INSERT INTO calibration(created_at, p1, p2, p3, p4_check, wobj, tool, active) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (_now(), *[json.dumps(p) for p in padded], json.dumps(wobj), json.dumps(stored_tool),
                 int(active)))
            return cur.lastrowid

    def get_active_calibration(self) -> dict | None:
        row = self._one("SELECT * FROM calibration WHERE active=1 ORDER BY id DESC LIMIT 1")
        if row is None:
            return None
        tool = _loads(row["tool"])
        pen_quat = None
        if isinstance(tool, dict):
            tool, pen_quat = tool.get("tool"), tool.get("pen_quat")
        return {"id": row["id"], "created_at": row["created_at"],
                "points": [_loads(row[k]) for k in ("p1", "p2", "p3", "p4_check")],
                "wobj": _loads(row["wobj"]), "tool": tool, "pen_quat": pen_quat}

    def clear_calibration(self) -> None:
        self._exec("UPDATE calibration SET active=0")
