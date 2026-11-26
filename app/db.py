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
    created_at TEXT, deleted INTEGER DEFAULT 0, speed_mode TEXT DEFAULT 'normal',
    profile_id INTEGER);
CREATE TABLE IF NOT EXISTS run_paths(run_id INTEGER PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS profiles(
    id INTEGER PRIMARY KEY, name TEXT, created_at TEXT, active INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS robot_runs(
    id INTEGER PRIMARY KEY, labyrinth_id INTEGER, time_ms INTEGER, speed REAL,
    timing_method TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS calibration(
    id INTEGER PRIMARY KEY, created_at TEXT, p1 TEXT, p2 TEXT, p3 TEXT, p4_check TEXT,
    wobj TEXT, tool TEXT, active INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS runs_board ON runs(labyrinth_id, status, deleted, time_ms);
"""

# Every leaderboard query only sees the runs of the active leaderboard profile.
ACTIVE_PROFILE = "(SELECT id FROM profiles WHERE active=1 ORDER BY id LIMIT 1)"
PROFILE_NAME_MAX = 40


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
            if "profile_id" not in columns:
                self._conn.execute("ALTER TABLE runs ADD COLUMN profile_id INTEGER")
            # There is always exactly one active leaderboard profile.
            if self._conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 0:
                self._conn.execute("INSERT INTO profiles(name, created_at, active) VALUES('Standard', ?, 1)",
                                   (_now(),))
            if self._conn.execute("SELECT COUNT(*) FROM profiles WHERE active=1").fetchone()[0] != 1:
                first = self._conn.execute("SELECT MIN(id) FROM profiles").fetchone()[0]
                self._conn.execute("UPDATE profiles SET active=(id=?)", (first,))
            # Runs from before profiles existed belong to the active profile.
            self._conn.execute(f"UPDATE runs SET profile_id={ACTIVE_PROFILE} WHERE profile_id IS NULL")

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
            "INSERT INTO runs(labyrinth_id, name, birth_year, time_ms, status, created_at, speed_mode, "
            f"profile_id) VALUES(?,?,?,?,?,?,?,{ACTIVE_PROFILE})",
            (labyrinth_id, name, birth_year, time_ms, status, _now(), speed_mode)).lastrowid

    def top_runs(self, labyrinth_id: int, limit: int = 10, speed_mode: str = "normal") -> list[dict]:
        """Best finished runs of one speed mode (every mode has its own board)."""
        rows = self._all(
            "SELECT id, name, birth_year, time_ms FROM runs WHERE labyrinth_id=? AND "
            "status='finished' AND deleted=0 AND speed_mode=? "
            f"AND profile_id={ACTIVE_PROFILE} ORDER BY time_ms, id LIMIT ?",
            (labyrinth_id, speed_mode, limit))
        return [dict(r) for r in rows]

    def placement(self, labyrinth_id: int, run_id: int) -> tuple[int, int] | None:
        """(rank, total) of a finished run among the finished runs of the same speed mode."""
        run = self._one("SELECT time_ms, speed_mode, profile_id FROM runs WHERE id=? AND "
                        "status='finished' AND deleted=0", (run_id,))
        if run is None:
            return None
        mode = run["speed_mode"]
        base = ("FROM runs WHERE labyrinth_id=? AND status='finished' AND deleted=0 AND speed_mode=? "
                "AND profile_id=?")
        better = self._one(f"SELECT COUNT(*) AS n {base} AND (time_ms < ? OR (time_ms = ? AND id < ?))",
                           (labyrinth_id, mode, run["profile_id"], run["time_ms"], run["time_ms"],
                            run_id))["n"]
        total = self._one(f"SELECT COUNT(*) AS n {base}", (labyrinth_id, mode, run["profile_id"]))["n"]
        return better + 1, total

    def list_runs(self, labyrinth_id: int, search: str = "", limit: int = 500) -> list[dict]:
        rows = self._all(
            "SELECT id, name, birth_year, time_ms, status, created_at, speed_mode, "
            "EXISTS(SELECT 1 FROM run_paths p WHERE p.run_id = runs.id) AS replay FROM runs "
            f"WHERE labyrinth_id=? AND deleted=0 AND profile_id={ACTIVE_PROFILE} AND name LIKE ? "
            "ORDER BY id DESC LIMIT ?",
            (labyrinth_id, f"%{search}%", limit))
        return [dict(r) for r in rows]

    def delete_run(self, run_id: int) -> None:
        self._exec("UPDATE runs SET deleted=1 WHERE id=?", (run_id,))

    def reset_runs(self, labyrinth_id: int) -> None:
        self._exec(f"UPDATE runs SET deleted=1 WHERE labyrinth_id=? AND profile_id={ACTIVE_PROFILE}",
                   (labyrinth_id,))

    def stats_runs(self, labyrinth_id: int) -> list[dict]:
        """All runs (finished and aborted) of the active profile, for the statistics page."""
        rows = self._all(
            "SELECT id, name, birth_year, time_ms, status, speed_mode, created_at, "
            "EXISTS(SELECT 1 FROM run_paths p WHERE p.run_id = runs.id) AS replay FROM runs "
            f"WHERE labyrinth_id=? AND deleted=0 AND profile_id={ACTIVE_PROFILE} ORDER BY id",
            (labyrinth_id,))
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- replays
    def save_run_path(self, run_id: int, data: dict) -> None:
        self._exec("INSERT OR REPLACE INTO run_paths(run_id, data) VALUES(?, ?)",
                   (run_id, json.dumps(data, separators=(",", ":"))))

    def run_path(self, run_id: int) -> dict | None:
        row = self._one("SELECT data FROM run_paths WHERE run_id=?", (run_id,))
        return _loads(row["data"]) if row else None

    def get_run(self, run_id: int) -> dict | None:
        row = self._one("SELECT id, labyrinth_id, name, birth_year, time_ms, status, speed_mode, created_at "
                        "FROM runs WHERE id=? AND deleted=0", (run_id,))
        return dict(row) if row else None

    def runs_revision(self) -> str:
        """Changes whenever a run is added or deleted or the profile changes (cheap)."""
        row = self._one(f"SELECT COUNT(*) AS n, IFNULL(MAX(id), 0) AS m, IFNULL(SUM(deleted), 0) AS d, "
                        f"{ACTIVE_PROFILE} AS p FROM runs")
        return f"{row['p']}-{row['n']}-{row['m']}-{row['d']}"

    def export_runs(self, profile_id: int) -> list[dict]:
        """Every run of one profile (without deleted ones), with the labyrinth name."""
        rows = self._all(
            "SELECT r.id, r.labyrinth_id, l.name AS labyrinth, r.name, r.birth_year, r.time_ms, r.status, "
            "r.speed_mode, r.created_at FROM runs r LEFT JOIN labyrinths l ON l.id = r.labyrinth_id "
            "WHERE r.profile_id=? AND r.deleted=0 ORDER BY r.id", (profile_id,))
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- profiles
    def profiles(self) -> list[dict]:
        rows = self._all(
            "SELECT p.id, p.name, p.created_at, p.active, "
            "(SELECT COUNT(*) FROM runs r WHERE r.profile_id=p.id AND r.deleted=0 AND r.status='finished') "
            "AS runs FROM profiles p ORDER BY p.id")
        return [{**dict(r), "active": bool(r["active"])} for r in rows]

    def active_profile(self) -> dict:
        row = self._one(f"SELECT id, name FROM profiles WHERE id={ACTIVE_PROFILE}")
        return dict(row)

    def profile(self, profile_id: int) -> dict | None:
        row = self._one("SELECT id, name, active FROM profiles WHERE id=?", (profile_id,))
        return dict(row) if row else None

    def add_profile(self, name: str) -> int:
        return self._exec("INSERT INTO profiles(name, created_at, active) VALUES(?, ?, 0)",
                          (name, _now())).lastrowid

    def rename_profile(self, profile_id: int, name: str) -> None:
        self._exec("UPDATE profiles SET name=? WHERE id=?", (name, profile_id))

    def activate_profile(self, profile_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE profiles SET active=(id=?)", (profile_id,))

    def delete_profile(self, profile_id: int) -> None:
        """Removes a profile and its runs for good (never the active one; checked by the caller)."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM runs WHERE profile_id=?", (profile_id,))
            self._conn.execute("DELETE FROM profiles WHERE id=? AND active=0", (profile_id,))

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
