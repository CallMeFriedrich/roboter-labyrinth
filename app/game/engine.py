"""Game engine: ties state machine, robot, labyrinth, timer and leaderboard together.

One instance per server process. All public coroutines are called from the
API layer; they raise `GameError` with a German message for the user.
"""
from __future__ import annotations

import asyncio
from datetime import date
import logging
import math
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from shapely.geometry import Point, Polygon

from ..db import PROFILE_NAME_MAX, Database
from ..geometry import frames
from ..geometry.channel import Channel
from ..geometry.frames import Frame
from ..geometry.labyrinth import LabyrinthRuntime
from ..geometry.lines import gate_from_taps, orient, suggest_gate
from ..geometry.pathfinding import PathError, estimate_time, plan_path
from ..geometry.svg_import import SvgImportError, parse_svg
from ..robot.driver_base import DriverError
from ..robot.driver_sim import SimDriver
from ..robot.jog_loop import JogLoop, KeyState
from ..robot.manager import DEFAULT_TOOL, RobotManager
from ..settings import ROOT, Config, SettingsStore
from .leaderboard import EntryError, Leaderboard, clean_birth_year, clean_name
from .state_machine import ABORTABLE, JOG_STATES, IllegalTransition, State, StateMachine
from .timer import RunTimer

log = logging.getLogger("game")
S = State

AUTO_REQUEST_TIMEOUT = 60.0
GEOMETRY_SETTINGS = {"pin_diameter", "wall_tolerance", "auto_extra_margin"}
IDLE_ONLY_SETTINGS = GEOMETRY_SETTINGS | {"driver", "viewer_side", "tool_roll_deg", "insert_depth",
                                          "retract_distance"}
SEED_SVG = ROOT / "tests" / "data" / "Labyrinth_Deckplatte_Entwurf1.svg"
ORIENTATION_TOLERANCE_DEG = 1.0   # head orientation may differ this much between holes
HOLE_APPROACH_CLEARANCE = 20.0    # mm in front of a predicted hole: the pen never hits the plate
SPEED_MODES = {"slow": "speed_slow", "normal": "visitor_speed", "turbo": "speed_turbo"}
WALL_HOLD_S = 5.0                # after touching the wall the robot stands still this long
WALL_ABORT_SLACK = 0.3          # mm: the slide along the limit counts as reaching it
HOLE_NEAR_CLEARANCE = 2.0         # "Näher ran": stop this far in front, the rest by hand


class GameError(Exception):
    """An action is not possible right now; the message goes to the user."""


class NullHub:
    async def send_public(self, message: dict) -> None: ...
    async def send_admin(self, message: dict) -> None: ...


class GameEngine:
    def __init__(self, config: Config, db: Database, hub: Any = None, seed: bool = True):
        self.config, self.db = config, db
        self.hub = hub or NullHub()
        self.settings = SettingsStore(db, config)
        self.board = Leaderboard(db)
        self.sm = StateMachine(self._state_changed)
        self.keys = KeyState()

        self.lab: LabyrinthRuntime | None = None
        self._lab_cache: dict[int, LabyrinthRuntime] = {}
        self._drivable_poly: Polygon | None = None
        self.lab_rev = 0
        self._seed = seed

        self.robot = RobotManager(config, self.settings, db, self._robot_connected, self._robot_lost,
                                  lambda: self._drivable_poly, self._plate_size)

        self.run: dict | None = None            # {"kind": "visitor"|"robot", "name", "birth_year"}
        self.timer: RunTimer | None = None
        self.countdown_end: float | None = None
        self.result: dict | None = None
        self.auto_result: dict | None = None
        self.auto_request_at: float | None = None
        self.message = ""                       # last problem, shown in the admin panel
        self.notice: str | None = None          # short visitor message while the robot goes back
        self.speed_mode = "normal"              # visitor choice: slow | normal | turbo
        self._recording: dict | None = None     # path of the running visitor run (for replays)
        self.replay: dict | None = None         # replay requested or running: run info + path
        self.replay_requested = False
        self.wall_hit: dict | None = None       # {"time_ms", "depth"} while a wall touch is shown
        self.cycle_ms = 0.0
        self.paused = False                     # admin hold: visitors may not start new runs

        self._run_task: asyncio.Task | None = None
        self._auto_timeout_task: asyncio.Task | None = None
        self._jog: JogLoop | None = None
        self._admin_lock = asyncio.Lock()
        self._hold: tuple[str, tuple[float, float, float], float] | None = None
        self._hold_task: asyncio.Task | None = None
        self._tasks: list[asyncio.Task] = []
        self._dirty = asyncio.Event()
        self.calib_points: dict[int, list[float]] = {
            int(k): v for k, v in (db.get_setting("calib_draft", {}) or {}).items()}
        self.last_hole_approach: dict | None = None   # {"index", "clearance", "target"} of the last "Hinfahren"
        self.calib_quats: dict[int, list[float]] = {
            int(k): v for k, v in (db.get_setting("calib_draft_q", {}) or {}).items()}

    # ================================================================ lifecycle
    async def start(self) -> None:
        self.db.backup(self.config.resolve(self.config.paths.backups))
        self._load_active_labyrinth()
        self.robot.start()
        self._tasks = [asyncio.create_task(self._broadcast_loop(), name="broadcast"),
                       asyncio.create_task(self._position_loop(), name="position")]
        await self.robot.connect()

    async def stop(self) -> None:
        for task in [self._run_task, self._hold_task, self._auto_timeout_task, *self._tasks]:
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*[t for t in [self._run_task, self._hold_task, *self._tasks] if t],
                             return_exceptions=True)
        await self.robot.stop()

    def notify(self) -> None:
        self._dirty.set()

    def _state_changed(self, old: State, new: State) -> None:
        log.info("Zustand %s → %s", old.value, new.value)
        self.notify()

    # =============================================================== labyrinth
    def _plate_size(self) -> tuple[float, float]:
        if self.lab is not None:
            return (self.lab.geometry.width, self.lab.geometry.height)
        return (frames.PLATE_SIZE, frames.PLATE_SIZE)

    def _build(self, record: dict) -> LabyrinthRuntime:
        return LabyrinthRuntime(record, self.settings["pin_diameter"], self.settings["wall_tolerance"])

    def runtime(self, labyrinth_id: int) -> LabyrinthRuntime:
        if labyrinth_id not in self._lab_cache:
            record = self.db.get_labyrinth(labyrinth_id)
            if record is None:
                raise GameError("Dieses Labyrinth gibt es nicht mehr.")
            try:
                self._lab_cache[labyrinth_id] = self._build(record)
            except SvgImportError as exc:
                raise GameError(str(exc)) from exc
        return self._lab_cache[labyrinth_id]

    def _set_active_runtime(self, runtime: LabyrinthRuntime | None) -> None:
        self.lab = runtime
        self._drivable_poly = (runtime.channel.allowed.buffer(0.3)
                               if runtime is not None and runtime.channel is not None else None)
        self.lab_rev += 1
        if self.robot.driver.connected:
            self.robot.driver.guard = self.robot._guard()
        self.notify()

    def _load_active_labyrinth(self) -> None:
        record = self.db.get_active_labyrinth()
        if record is None and self._seed and not self.db.list_labyrinths() and SEED_SVG.exists():
            try:
                labyrinth_id = self._import("Entwurf 1", SEED_SVG.read_text(encoding="utf-8"))
                self.compute_path(labyrinth_id)
                self.db.set_active_labyrinth(labyrinth_id)
                record = self.db.get_labyrinth(labyrinth_id)
                log.info("Entwurf 1 als erstes Labyrinth eingespielt")
            except GameError as exc:
                log.warning("Entwurf 1 konnte nicht eingespielt werden: %s", exc)
        if record is not None:
            try:
                self._set_active_runtime(self.runtime(record["id"]))
            except GameError as exc:
                self.message = str(exc)

    def _refresh(self, labyrinth_id: int) -> LabyrinthRuntime:
        """Rebuild a labyrinth after its record changed."""
        self._lab_cache.pop(labyrinth_id, None)
        runtime = self.runtime(labyrinth_id)
        if self.lab is not None and self.lab.id == labyrinth_id:
            self._set_active_runtime(runtime)
        return runtime

    def _require_idle(self) -> None:
        if self.sm.state not in (S.DISCONNECTED, S.IDLE):
            raise GameError("Das geht nur, wenn gerade kein Lauf aktiv ist.")

    def _import(self, name: str, svg: str) -> int:
        try:
            parse_svg(svg)
        except SvgImportError as exc:
            raise GameError(str(exc)) from exc
        labyrinth_id = self.db.add_labyrinth(name.strip()[:60] or "Labyrinth", svg)
        runtime = self.runtime(labyrinth_id)
        start, finish = runtime.gate_records()
        if start is not None:
            self.db.update_labyrinth(labyrinth_id, start_line=start, finish_line=finish)
            self._lab_cache.pop(labyrinth_id, None)
        return labyrinth_id

    def upload_labyrinth(self, name: str, svg: str) -> int:
        if len(svg) > 5_000_000:
            raise GameError("Die Datei ist zu groß.")
        return self._import(name, svg)

    def labyrinth_detail(self, labyrinth_id: int) -> dict:
        runtime = self.runtime(labyrinth_id)
        data = runtime.to_client()
        data["active"] = self.lab is not None and self.lab.id == labyrinth_id
        if runtime.path is not None:
            accel = self.robot.acceleration
            data["estimates"] = {
                "auto_s": round(estimate_time(runtime.path.timed_length, self.settings["auto_speed"], accel), 2),
                "visitor_s": round(runtime.path.timed_length / self.settings["visitor_speed"], 1)}
        return data

    def _save_gates(self, runtime: LabyrinthRuntime) -> LabyrinthRuntime:
        self._require_idle()
        start, finish = runtime.gate_records()
        self.db.update_labyrinth(runtime.id, start_line=start, finish_line=finish, path=None)
        return self._refresh(runtime.id)

    def _spot_at(self, runtime: LabyrinthRuntime, p: tuple[float, float]) -> dict | None:
        for spot in runtime.spots:
            if math.dist(spot["center"], p) <= spot["radius"]:
                return spot
        return None

    def set_point(self, labyrinth_id: int, which: str, p: tuple[float, float]) -> None:
        """Set start or finish point; inside a circle the gate is suggested automatically."""
        runtime = self.runtime(labyrinth_id)
        if which not in ("start", "finish"):
            raise GameError("Unbekannter Punkt.")
        if not runtime.geometry.channel.covers(Point(p)):
            raise GameError("Der Punkt liegt nicht im Kanal.")
        spot = self._spot_at(runtime, p)
        point = tuple(spot["center"]) if spot else (float(p[0]), float(p[1]))
        gate = None
        if spot is not None:
            try:
                gate = suggest_gate(runtime.geometry.channel, spot["center"], spot["radius"], which == "start")
            except ValueError:
                gate = None
        if which == "start":
            runtime.start_point = point
            runtime.start_gate = gate or runtime.start_gate
        else:
            runtime.finish_point = point
            runtime.finish_gate = gate or runtime.finish_gate
        if runtime.start_gate and runtime.finish_gate and runtime.start_point and runtime.finish_point:
            self._save_gates(runtime)
        # otherwise the point stays in the cached runtime until both lines are set

    def swap_start_finish(self, labyrinth_id: int) -> None:
        runtime = self.runtime(labyrinth_id)
        if not (runtime.start_gate and runtime.finish_gate):
            raise GameError("Es sind noch keine Linien festgelegt.")
        runtime.start_point, runtime.finish_point = runtime.finish_point, runtime.start_point
        runtime.start_gate, runtime.finish_gate = runtime.finish_gate.reversed(), runtime.start_gate.reversed()
        self._save_gates(runtime)

    def set_gate(self, labyrinth_id: int, which: str, p: tuple[float, float], q: tuple[float, float]) -> None:
        runtime = self.runtime(labyrinth_id)
        try:
            gate = gate_from_taps(runtime.geometry.channel, p, q)
        except ValueError as exc:
            raise GameError(str(exc)) from exc
        if which == "start" and runtime.start_point:
            runtime.start_gate = orient(gate, runtime.start_point, away=True)
        elif which == "finish" and runtime.finish_point:
            runtime.finish_gate = orient(gate, runtime.finish_point, away=False)
        else:
            raise GameError("Bitte zuerst Start und Ziel festlegen.")
        if runtime.start_gate and runtime.finish_gate:
            self._save_gates(runtime)

    def flip_gate(self, labyrinth_id: int, which: str) -> None:
        runtime = self.runtime(labyrinth_id)
        if which == "start" and runtime.start_gate:
            runtime.start_gate = runtime.start_gate.reversed()
        elif which == "finish" and runtime.finish_gate:
            runtime.finish_gate = runtime.finish_gate.reversed()
        else:
            raise GameError("Diese Linie gibt es noch nicht.")
        self._save_gates(runtime)

    def compute_path(self, labyrinth_id: int) -> dict:
        self._require_idle()
        runtime = self.runtime(labyrinth_id)
        if runtime.channel is None or not (runtime.start_gate and runtime.finish_gate):
            raise GameError("Bitte zuerst Start, Ziel und beide Linien festlegen.")
        try:
            path = plan_path(runtime.auto_channel.allowed, self.settings["auto_extra_margin"],
                             runtime.start_point, runtime.finish_point,
                             runtime.start_gate, runtime.finish_gate)
        except PathError as exc:
            raise GameError(str(exc)) from exc
        self.db.update_labyrinth(labyrinth_id, path=path.to_dict())
        self._refresh(labyrinth_id)
        return path.to_dict()

    def activate_labyrinth(self, labyrinth_id: int) -> None:
        self._require_idle()
        runtime = self.runtime(labyrinth_id)
        if not runtime.ready:
            raise GameError("Das Labyrinth ist noch nicht vollständig: Linien setzen und Weg berechnen.")
        self.db.set_active_labyrinth(labyrinth_id)
        self._set_active_runtime(runtime)

    def delete_labyrinth(self, labyrinth_id: int) -> None:
        if self.lab is not None and self.lab.id == labyrinth_id:
            raise GameError("Das aktive Labyrinth kann nicht gelöscht werden.")
        self.db.delete_labyrinth(labyrinth_id)
        self._lab_cache.pop(labyrinth_id, None)

    # ================================================================ settings
    def _check_no_shortcut(self, values: dict[str, Any]) -> None:
        """A negative tolerance must never let the pen drive through a wall of the active labyrinth."""
        pin = values.get("pin_diameter", self.settings["pin_diameter"])
        tol = values.get("wall_tolerance", self.settings["wall_tolerance"])
        if not isinstance(pin, (int, float)) or not isinstance(tol, (int, float)) or tol >= 0:
            return
        channel = self.lab.geometry.channel
        try:
            bridged = Channel(channel, float(pin), float(tol)).bridged_walls()
        except ValueError:
            return                                   # reported by the normal validation
        if not bridged:
            return
        lowest = 0.0
        while lowest - 0.5 >= tol and not Channel(channel, float(pin), lowest - 0.5).bridged_walls():
            lowest -= 0.5
        raise GameError(f"Bei {tol:g} mm könnte der Stift durch eine Wand abkürzen. "
                        f"Bei diesem Labyrinth geht höchstens {lowest:g} mm.")

    async def patch_settings(self, values: dict[str, Any]) -> None:
        if not isinstance(values, dict) or not values:
            raise GameError("Keine Einstellungen übergeben.")
        changed = {k for k, v in values.items() if k in self.settings.all() and self.settings[k] != v}
        if changed & IDLE_ONLY_SETTINGS:
            self._require_idle()
            if self._admin_lock.locked():
                raise GameError("Der Roboter führt gerade einen Befehl aus.")
        if changed & {"wall_tolerance", "pin_diameter"} and self.lab is not None:
            self._check_no_shortcut(values)
        try:
            self.settings.patch(values)
        except ValueError as exc:
            raise GameError(str(exc)) from exc
        if changed & GEOMETRY_SETTINGS:
            self._lab_cache.clear()
            if self.lab is not None:
                labyrinth_id = self.lab.id
                try:
                    self.db.update_labyrinth(labyrinth_id, path=None)
                    self.compute_path(labyrinth_id)
                except GameError as exc:
                    self._refresh(labyrinth_id)
                    self.message = f"Der Weg konnte nicht neu berechnet werden: {exc}"
        if "driver" in changed:
            if self.sm.state == S.IDLE:
                self.sm.to(S.DISCONNECTED)
            await self.robot.set_driver(self.settings["driver"])
            self.robot.want_connected = True
            await self.robot.connect()
        self._refresh_idle()
        self.notify()

    # ============================================================ robot events
    async def _robot_connected(self) -> None:
        self.message = ""
        if isinstance(self.robot.driver, SimDriver) and self.config.sim.auto_home:
            try:
                await self.robot.go_home()
            except (DriverError, ValueError) as exc:
                self.message = str(exc)
        self._refresh_idle()
        self.notify()

    async def _robot_lost(self, message: str) -> None:
        task = self._run_task
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
        await self._fail(f"Verbindung zum Roboter verloren: {message}")

    def _refresh_idle(self) -> None:
        """DISCONNECTED ↔ IDLE depending on connection and confirmed home position."""
        ready = self.robot.connected and self.robot.home_confirmed
        if self.sm.state == S.DISCONNECTED and ready:
            self.sm.to(S.IDLE)
        elif self.sm.state == S.IDLE and not ready:
            self.sm.to(S.DISCONNECTED)

    async def _fail(self, message: str) -> None:
        """Any state → ERROR → DISCONNECTED. No further moves until an admin homes the robot."""
        self.message = message
        log.error("Spiel angehalten: %s", message)
        self._stop_jog()
        self.keys.clear()
        self.run = self.timer = self.countdown_end = self.auto_request_at = None
        self.robot.home_confirmed = False
        if self.sm.state not in (S.ERROR, S.DISCONNECTED):
            self.sm.to(S.ERROR)
            await self.hub.send_admin({"type": "error", "message": message})
            await self.hub.send_public(self.snapshot())
        if self.sm.state == S.ERROR:
            self.sm.to(S.DISCONNECTED)
        self.notify()

    async def _guarded(self, sequence) -> None:
        try:
            await sequence()
        except asyncio.CancelledError:
            raise
        except DriverError as exc:
            await self._fail(f"Verbindung zum Roboter verloren: {exc}")
        except (ValueError, IllegalTransition, GameError) as exc:
            await self._fail(f"Der Lauf wurde angehalten: {exc}")
        except Exception as exc:    # unknown error → safe state
            log.exception("Unerwarteter Fehler im Lauf")
            await self._fail(f"Unerwarteter Fehler: {exc}")

    # ============================================================== readiness
    def why_not(self) -> str | None:
        """Reason why no run can start right now (None = ready)."""
        state = self.sm.state
        if state in (S.DISCONNECTED, S.ERROR):
            if not self.robot.connected:
                return "Der Roboter ist nicht verbunden."
            return "Home ist noch nicht bestätigt."
        if state != S.IDLE:
            return "Es läuft gerade ein Lauf."
        if self.lab is None or not self.lab.ready:
            return "Das Labyrinth ist noch nicht fertig eingerichtet."
        if self.robot.plate_frame is None:
            return "Die Platte ist noch nicht eingemessen."
        if self.paused:
            return "Die Besucher sind pausiert."
        if self._admin_lock.locked():
            return "Der Roboter ist gerade beschäftigt."
        return None

    def _lab_problem(self) -> str | None:
        lab = self.lab
        if lab is None:
            return "Es ist kein Labyrinth aktiv."
        if lab.channel is None:
            return "Der Kanal ist mit diesem Stift und dieser Wandtoleranz nicht befahrbar."
        if lab.start_gate is None or lab.finish_gate is None:
            return "Start- und Ziellinie fehlen noch."
        if lab.path is None or lab.path.start_index is None or lab.path.finish_index is None:
            return "Der kürzeste Weg ist noch nicht berechnet."
        return None

    def readiness(self) -> list[dict]:
        """Checklist for the admin: what visitors need before they can start, and how to fix it."""
        connected = self.robot.connected
        lab_problem = self._lab_problem()
        calibrated = self.robot.plate_frame is not None
        active = self.sm.state not in (S.DISCONNECTED, S.ERROR, S.IDLE)
        return [
            {"key": "robot", "label": "Roboter verbunden", "ok": connected,
             "detail": None if connected else (self.robot.last_error or "Keine Verbindung zum Roboter."),
             "fix": None if connected else "connect"},
            {"key": "labyrinth", "label": "Labyrinth eingerichtet", "ok": lab_problem is None,
             "detail": lab_problem, "fix": None if lab_problem is None else "labyrinth"},
            {"key": "calibration", "label": "Platte eingemessen", "ok": calibrated,
             "detail": None if calibrated else "Ohne Einmessen weiß der Roboter nicht, wo die Platte ist.",
             "fix": None if calibrated else "calibration"},
            {"key": "home", "label": "Home bestätigt", "ok": self.robot.home_confirmed or active,
             "detail": None if self.robot.home_confirmed or active else
                       ("Nach dem Verbinden oder Fahren von Hand muss der Roboter einmal Home anfahren."
                        if connected else "Geht erst, wenn der Roboter verbunden ist."),
             "fix": None if self.robot.home_confirmed or active or not connected else "home"},
            {"key": "released", "label": "Besucher freigegeben", "ok": not self.paused,
             "detail": "Du hast die Besucher pausiert." if self.paused else None,
             "fix": "release" if self.paused else None},
        ]

    def release(self) -> None:
        self.paused = False
        log.info("Besucher freigegeben")
        self.notify()

    def pause(self) -> None:
        self.paused = True
        log.info("Besucher pausiert")
        self.notify()

    # ============================================================= visitor run
    def set_keys(self, down) -> None:
        if self.sm.state in JOG_STATES:
            self.keys.update(down)
        else:
            self.keys.clear()

    async def start_run(self, name: Any, birth_year: Any) -> None:
        try:
            name, birth_year = clean_name(name), clean_birth_year(birth_year)
        except EntryError as exc:
            raise GameError(str(exc)) from exc
        reason = self.why_not()
        if reason is not None:
            raise GameError(reason)
        self.run = {"kind": "visitor", "name": name, "birth_year": birth_year, "speed_mode": self.speed_mode}
        self.result = self.auto_result = None
        self.timer = RunTimer(self.lab.start_gate, self.lab.finish_gate)
        self.keys.clear()
        self.sm.to(S.MOVING_TO_START)
        self._run_task = asyncio.create_task(self._guarded(self._visitor_run), name="visitor-run")

    SOUND_NAMES = ("win", "record", "wall", "giveup")

    async def sound_test(self, name: str) -> None:
        """Admin: play a sound on the visitor screen (to set the volume on site)."""
        if name not in self.SOUND_NAMES:
            raise GameError("Unbekannter Ton.")
        await self.hub.send_public({"type": "sound", "name": name})

    def speeds(self) -> dict[str, float]:
        return {mode: float(self.settings[key]) for mode, key in SPEED_MODES.items()}

    def visitor_speed(self) -> float:
        mode = self.run.get("speed_mode", "normal") if self.run else self.speed_mode
        return float(self.settings[SPEED_MODES.get(mode, "visitor_speed")])

    def set_speed_mode(self, mode: Any) -> None:
        if mode not in SPEED_MODES:
            raise GameError("Unbekannte Geschwindigkeit.")
        if self.sm.state != S.IDLE:
            raise GameError("Die Geschwindigkeit lässt sich nur vor dem Start wählen.")
        self.speed_mode = mode
        self.notify()

    def _stop_jog(self) -> None:
        if self._jog is not None:
            self._jog.stop()

    async def _visitor_run(self) -> None:
        lab, timer, run = self.lab, self.timer, self.run
        start = lab.channel.snap(lab.start_point)
        await self.robot.go_to(start)

        countdown = self.settings["countdown_s"]
        if countdown > 0:
            self.countdown_end = time.monotonic() + countdown
            self.sm.to(S.COUNTDOWN)
            await asyncio.sleep(countdown)
            self.countdown_end = None
        self.keys.clear()
        self.sm.to(S.ARMED)

        finished = asyncio.Event()
        z = self.robot.insert_z()
        wall_hit: list[float] = []
        rec_t0 = time.monotonic_ns()
        recording = {"t0": rec_t0, "mode": run.get("speed_mode", "normal"),
                     "points": [[0, round(start[0], 1), round(start[1], 1)]]}
        self._recording = recording

        def on_segment(p0, p1, t0_ns, t1_ns) -> None:
            recording["points"].append([round((t1_ns - rec_t0) / 1e6), round(p1[0], 1), round(p1[1], 1)])
            event = timer.feed(p0, p1, t0_ns, t1_ns)
            if event == "started":
                self.sm.to(S.RUNNING)
            elif event == "finished":
                jog.stop()
                finished.set()
            self.cycle_ms = jog.cycle_ms
            limit = self.settings["wall_abort_depth"] if self.settings["wall_abort"] == "on" else 0
            if limit > 0 and not finished.is_set() and not wall_hit:
                depth = lab.channel.wall_depth(p1)
                if depth >= limit - WALL_ABORT_SLACK:
                    wall_hit.append(depth)
                    jog.stop()
                    if timer.running:
                        timer.finish_now(t1_ns)          # the clock stops at the touch

        async def move(p) -> None:
            await self.robot.move_plate(p[0], p[1], z, self.visitor_speed(),
                                        self.settings["jog_zone"], "visitor")

        jog = JogLoop(start=start, keys=self.keys.active, constrain=lab.channel.constrain, move=move,
                      on_segment=on_segment, speed=self.visitor_speed,
                      rate_hz=lambda: self.settings["jog_rate_hz"])
        self._jog = jog
        jog_task = asyncio.create_task(jog.run(), name="jog")
        try:
            await jog_task                      # ends when the finish gate was crossed
        finally:
            jog.stop()
            self._jog = None
            if not jog_task.done():
                jog_task.cancel()
                await asyncio.gather(jog_task, return_exceptions=True)
        if wall_hit:
            await self._wall_out(run, wall_hit[0])
            return
        if not finished.is_set():
            raise GameError("Die Steuerung wurde unerwartet beendet.")

        self.keys.clear()
        self.speed_mode = "normal"              # every new visitor starts on "Normal" again
        self.result = self.board.add_finished(lab.id, run["name"], run["birth_year"], timer.time_ms,
                                              run.get("speed_mode", "normal"))
        self._save_recording(self.result["run_id"], "finished")
        self.sm.to(S.FINISHED)
        shown_since = time.monotonic()
        await self.hub.send_public({"type": "result", **self.result})
        self.sm.to(S.RETURNING_HOME)
        await self.robot.go_home()
        rest = self.settings["result_display_s"] - (time.monotonic() - shown_since)
        if rest > 0:
            await asyncio.sleep(rest)
        self._end_run()

    async def _wall_out(self, run: dict, depth: float) -> None:
        """Pen too deep in a wall: time stops, the robot stays where it is for a moment, then home."""
        time_ms = self.timer.elapsed_ms() if self.timer else 0
        log.info("Lauf von %s beendet: %.1f mm in der Wand nach %d ms", run["name"], depth, time_ms)
        self.keys.clear()
        if self.lab is not None:
            run_id = self.board.add_aborted(self.lab.id, run["name"], run["birth_year"],
                                            run.get("speed_mode", "normal"))
            self._save_recording(run_id, "wall")
        self.wall_hit = {"time_ms": time_ms, "depth": round(depth, 1)}
        self.notice = "Wand berührt – der Roboter bleibt kurz stehen."
        self.sm.to(S.ABORTING)
        await asyncio.sleep(WALL_HOLD_S)            # everybody can see where it touched
        self.notice = "Wand berührt – der Roboter fährt zurück …"
        self.sm.to(S.RETURNING_HOME)
        await self.robot.go_home()
        self._end_run()

    def _save_recording(self, run_id: int, end: str) -> None:
        """Store the steered path of a run so it can be replayed (virtually or with the robot)."""
        rec, self._recording = self._recording, None
        if not rec or len(rec["points"]) < 2:
            return
        timer, t0 = self.timer, rec["t0"]
        offset = lambda ns: round((ns - t0) / 1e6) if ns is not None else None   # noqa: E731
        self.db.save_run_path(run_id, {
            "v": 1, "mode": rec["mode"], "end": end, "points": rec["points"],
            "start_ms": offset(timer.started_ns) if timer else None,
            "finish_ms": offset(timer.finished_ns) if timer else None})

    def _end_run(self) -> None:
        self.notice = None
        self.replay = None
        self.replay_requested = False
        self.wall_hit = None
        self.run = self.timer = self.result = self.auto_result = None
        self.sm.to(S.IDLE)
        self._refresh_idle()

    async def give_up(self) -> None:
        if self.sm.state == S.AUTO_REQUESTED:
            await self.reject_auto()
        elif self.run is not None and self.run["kind"] == "visitor":
            await self.abort()

    async def abort(self) -> None:
        """Visitor gives up or admin aborts: stop steering, pull out, go home. No entry."""
        if self.sm.state == S.AUTO_REQUESTED:
            await self.reject_auto()
            return
        if self.sm.state not in ABORTABLE:
            return
        task, run = self._run_task, self.run
        self.sm.to(S.ABORTING)
        self._stop_jog()
        self.keys.clear()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self.sm.state != S.ABORTING:       # failed in the meantime
            return
        if run is not None and run["kind"] == "visitor" and self.lab is not None:
            run_id = self.board.add_aborted(self.lab.id, run["name"], run["birth_year"],
                                            run.get("speed_mode", "normal"))
            self._save_recording(run_id, "aborted")
        self._recording = None
        self.run = self.timer = self.countdown_end = None
        self._run_task = asyncio.create_task(self._guarded(self._return_home), name="return-home")

    async def _return_home(self) -> None:
        self.sm.to(S.RETURNING_HOME)
        await self.robot.go_home()
        self._end_run()

    # ================================================================ auto run
    async def request_auto(self) -> None:
        reason = self.why_not()
        if reason is not None:
            raise GameError(reason)
        self.auto_request_at = time.monotonic()
        self.sm.to(S.AUTO_REQUESTED)
        self._auto_timeout_task = asyncio.create_task(self._auto_timeout())

    async def _auto_timeout(self) -> None:
        await asyncio.sleep(AUTO_REQUEST_TIMEOUT)
        if self.sm.state == S.AUTO_REQUESTED:
            self.auto_request_at = None
            self.replay, self.replay_requested = None, False
            self.sm.to(S.IDLE)
            self._refresh_idle()

    async def reject_auto(self) -> None:
        if self.sm.state != S.AUTO_REQUESTED:
            return
        if self._auto_timeout_task is not None:
            self._auto_timeout_task.cancel()
        self.auto_request_at = None
        self.replay, self.replay_requested = None, False
        self.sm.to(S.IDLE)
        self._refresh_idle()

    async def start_auto(self) -> None:
        """Admin: approve a request or start the robot run directly."""
        if self.sm.state == S.AUTO_REQUESTED:
            if self._auto_timeout_task is not None:
                self._auto_timeout_task.cancel()
            self.auto_request_at = None
            if not (self.robot.connected and self.robot.home_confirmed and self.lab and self.lab.ready):
                self.sm.to(S.IDLE)
                self._refresh_idle()
                raise GameError("Der Roboter ist nicht mehr bereit.")
        else:
            reason = self.why_not()
            if reason is not None:
                raise GameError(reason)
        if self.replay is not None:              # approving a replay request
            self._begin_replay()
            return
        self.run = {"kind": "robot", "name": "Roboter", "birth_year": None}
        self.result = self.auto_result = None
        self.timer = RunTimer(self.lab.start_gate, self.lab.finish_gate)
        self.sm.to(S.AUTO_RUN)
        self._run_task = asyncio.create_task(self._guarded(self._auto_run), name="auto-run")

    def effective_timing_method(self) -> str:
        method = self.settings["timing_method"]
        if method == "logger" and not self.robot.driver.has_actual_position:
            return "fine"
        return method

    async def _sample_crossings(self, timer: RunTimer) -> None:
        """Timing method "logger": detect the gates in the measured position."""
        previous, previous_ns = None, 0
        while timer.finished_ns is None:
            position = self.robot.driver.actual_position()
            now_ns = time.monotonic_ns()
            if position is not None:
                if previous is not None and timer.feed(previous[:2], position[:2], previous_ns, now_ns):
                    self.notify()
                previous, previous_ns = position, now_ns
            await asyncio.sleep(0.004)

    async def _auto_run(self) -> None:
        lab, timer = self.lab, self.timer
        path = lab.path
        points, si, fi = path.points, path.start_index, path.finish_index
        speed, z = self.settings["auto_speed"], self.robot.insert_z()
        method = self.effective_timing_method()
        await self.robot.go_to(points[0])

        if method == "fine":
            # Stop on both gates; the answer times of the path pieces are the timer.
            await self.robot.run_plate_path(points[1:si + 1], z, speed, "z1")
            timer.start_now()
            self.notify()
            await self.robot.run_plate_path(points[si + 1:fi + 1], z, speed, "z1")
            timer.finish_now()
            self.notify()
            await self.robot.run_plate_path(points[fi + 1:], z, speed, "z1")
        elif method == "logger":
            sampler = asyncio.create_task(self._sample_crossings(timer))
            try:
                await self.robot.run_plate_path(points[1:], z, speed, "z1")
                await asyncio.wait_for(asyncio.shield(sampler), 0.3)
            except asyncio.TimeoutError:
                pass
            finally:
                sampler.cancel()
            if timer.finished_ns is None:
                method = "analytic"
                self.message = "LOGGER hat die Linien nicht erkannt – Zeit wurde berechnet."
        else:
            timer.start_now()
            self.notify()
            await self.robot.run_plate_path(points[1:], z, speed, "z1")
        if method == "analytic":
            duration = estimate_time(path.timed_length, speed, self.robot.acceleration)
            timer.start_now(time.monotonic_ns() - int(duration * 1e9))
            timer.finish_now()

        time_ms = timer.time_ms
        previous_best = self.board.robot_best(lab.id)
        self.db.add_robot_run(lab.id, time_ms, speed, method)
        self.auto_result = {"time_ms": time_ms, "method": method,
                            "new_best": previous_best is None or time_ms < previous_best}
        shown_since = time.monotonic()
        self.sm.to(S.RETURNING_HOME)
        await self.robot.go_home()
        rest = min(self.settings["result_display_s"], 5) - (time.monotonic() - shown_since)
        if rest > 0:
            await asyncio.sleep(rest)
        self._end_run()

    # ================================================================== replays
    def _replay_source(self, run_id: int) -> dict:
        run = self.db.get_run(run_id)
        path = self.db.run_path(run_id) if run else None
        if run is None or path is None:
            raise GameError("Für diesen Lauf gibt es keine Aufzeichnung.")
        if self.lab is None or run["labyrinth_id"] != self.lab.id:
            raise GameError("Dieser Lauf war auf einem anderen Labyrinth.")
        return {"run_id": run["id"], "name": run["name"], "birth_year": run["birth_year"],
                "time_ms": run["time_ms"], "status": run["status"], "end": path.get("end", run["status"]),
                "mode": path.get("mode", run["speed_mode"]), "path": path}

    def replay_data(self, run_id: int) -> dict:
        """Public: everything a screen needs to replay a run virtually."""
        source = self._replay_source(run_id)
        return {key: source[key] for key in ("run_id", "name", "birth_year", "time_ms", "status", "end", "mode")} \
            | {"path": source["path"]}

    def map_data(self) -> dict | None:
        """Public: the drawing of the active labyrinth (no admin details)."""
        if self.lab is None:
            return None
        data = self.lab.to_client()
        return {key: data[key] for key in ("width", "height", "channel", "engraving", "markers",
                                           "start_gate", "finish_gate", "start_point", "finish_point")}

    async def request_replay(self, run_id: int) -> None:
        """Stats iPad: a visitor wants to see a run again with the real robot; an admin approves."""
        source = self._replay_source(run_id)
        reason = self.why_not()
        if reason is not None:
            raise GameError(reason)
        self.replay, self.replay_requested = source, True
        self.auto_request_at = time.monotonic()
        self.sm.to(S.AUTO_REQUESTED)
        self._auto_timeout_task = asyncio.create_task(self._auto_timeout())

    async def start_replay(self, run_id: int) -> None:
        """Admin: replay a run with the robot right away."""
        source = self._replay_source(run_id)
        reason = self.why_not()
        if reason is not None:
            raise GameError(reason)
        self.replay = source
        self._begin_replay()

    def _begin_replay(self) -> None:
        source = self.replay
        self.replay_requested = False
        self.run = {"kind": "replay", "name": source["name"], "birth_year": source["birth_year"],
                    "speed_mode": source["mode"]}
        self.result = self.auto_result = None
        self.timer = RunTimer(self.lab.start_gate, self.lab.finish_gate)
        self.sm.to(S.AUTO_RUN)
        self._run_task = asyncio.create_task(self._guarded(self._replay_run), name="replay")

    async def _replay_run(self) -> None:
        """Drive a recorded path again: same rhythm (pauses included), today's walls and speed limits."""
        lab, timer, source = self.lab, self.timer, self.replay
        points = source["path"]["points"]
        speed = self.settings[SPEED_MODES.get(source["mode"], "visitor_speed")]
        z = self.robot.insert_z()
        previous = lab.channel.snap((points[0][1], points[0][2]))
        await self.robot.go_to(previous)
        began, t_first = time.monotonic(), points[0][0]
        for t_ms, x, y in points[1:]:
            lag = began + (t_ms - t_first) / 1000 - time.monotonic()
            if lag > 0.12:                        # the visitor paused here: pause too
                await asyncio.sleep(lag - 0.04)
            target = lab.channel.constrain(previous, (x, y))   # never outside today's allowed area
            if math.hypot(target[0] - previous[0], target[1] - previous[1]) < 0.05:
                continue
            t0 = time.monotonic_ns()
            await self.robot.move_plate(target[0], target[1], z, speed, self.settings["jog_zone"], "visitor")
            if timer.feed(previous, target, t0, time.monotonic_ns()):
                self.notify()
            previous = target
        if timer.running:
            timer.finish_now()
        self.sm.to(S.RETURNING_HOME)
        shown_since = time.monotonic()
        await self.robot.go_home()
        rest = 3 - (time.monotonic() - shown_since)
        if rest > 0:
            await asyncio.sleep(rest)
        self._end_run()

    def replay_public(self) -> dict | None:
        source = self.replay
        if source is None:
            return None
        return {"run_id": source["run_id"], "name": source["name"], "time_ms": source["time_ms"],
                "status": source["status"], "end": source["end"], "mode": source["mode"],
                "requested": self.replay_requested}

    # ============================================================ admin: robot
    @asynccontextmanager
    async def _admin_motion(self, need_connection: bool = True):
        self._require_idle()
        if need_connection and not self.robot.connected:
            raise GameError("Der Roboter ist nicht verbunden.")
        if self._admin_lock.locked():
            raise GameError("Der Roboter führt gerade einen anderen Befehl aus.")
        async with self._admin_lock:
            try:
                yield
            except DriverError as exc:
                raise GameError(f"Verbindung zum Roboter verloren: {exc}") from exc
            except ValueError as exc:
                raise GameError(str(exc)) from exc
            finally:
                self._refresh_idle()
                self.notify()

    async def connect(self) -> None:
        self._require_idle()
        await self.robot.connect()
        if not self.robot.connected:
            raise GameError(self.robot.last_error or "Keine Verbindung zum Roboter.")
        self.notify()

    async def disconnect(self) -> None:
        self._require_idle()
        await self.robot.disconnect()
        self._refresh_idle()
        self.notify()

    async def go_home(self) -> None:
        async with self._admin_motion():
            await self.robot.go_home()

    async def go_start_pose(self) -> None:
        async with self._admin_motion():
            await self.robot.move_joints(self.config.robot.home_joints)
            self.robot.home_confirmed = False

    async def teach_home(self) -> list[float]:
        async with self._admin_motion():
            joints = await self.robot.read_joints()
            self.db.set_setting("home_joints", joints)
            self.robot.home_confirmed = False
            return joints

    async def set_frame(self, mode: str) -> None:
        if mode not in ("base", "plate"):
            raise GameError("Unbekanntes Koordinatensystem.")
        async with self._admin_motion():
            if mode == "plate" and self.robot.plate_frame is None:
                raise GameError("Die Platte ist noch nicht eingemessen.")
            await self.robot.apply_frame(mode)

    @staticmethod
    def _direction(raw) -> tuple[float, float, float]:
        try:
            d = tuple(float(v) for v in raw)
        except (TypeError, ValueError):
            raise GameError("Ungültige Richtung.") from None
        if len(d) != 3 or not all(math.isfinite(v) for v in d):
            raise GameError("Ungültige Richtung.")
        length = math.sqrt(sum(v * v for v in d))
        return (0.0, 0.0, 0.0) if length < 1e-9 else tuple(v / length for v in d)

    async def jog_step(self, frame: str, direction, step: float) -> None:
        if step not in (0.1, 1, 1.0, 10, 10.0):
            raise GameError("Erlaubte Schrittweiten: 0,1 · 1 · 10 mm.")
        d = self._direction(direction)
        async with self._admin_motion():
            await self.robot.jog(frame, tuple(v * step for v in d), "fine")

    async def move_to(self, frame: str, target) -> list[float]:
        """Admin: drive straight to a coordinate in the base or plate frame (slow, fine zone)."""
        try:
            xyz = tuple(float(v) for v in target)
        except (TypeError, ValueError):
            raise GameError("Bitte drei Zahlen für X, Y und Z eingeben.") from None
        if len(xyz) != 3 or not all(math.isfinite(v) for v in xyz):
            raise GameError("Bitte drei Zahlen für X, Y und Z eingeben.")
        if frame not in ("base", "plate"):
            raise GameError("Unbekanntes Koordinatensystem.")
        async with self._admin_motion():
            await self.robot.move_to(frame, xyz)
        return [round(v, 2) for v in xyz]

    async def jog_hold(self, frame: str, direction) -> None:
        """Heartbeat of the hold-to-move pad; a zero direction stops."""
        self._hold = (frame, self._direction(direction), time.monotonic())
        if self._hold[1] != (0.0, 0.0, 0.0) and (self._hold_task is None or self._hold_task.done()):
            self._hold_task = asyncio.create_task(self._hold_loop(), name="admin-jog")

    async def _hold_loop(self) -> None:
        period = 0.1
        try:
            async with self._admin_motion():
                while self._hold is not None:
                    frame, d, stamp = self._hold
                    tick = time.monotonic()
                    if d == (0.0, 0.0, 0.0) or tick - stamp > 0.3:
                        break
                    step = self.config.robot.admin_jog_speed * period
                    await self.robot.jog(frame, tuple(v * step for v in d), "z1")
                    await asyncio.sleep(max(0.0, period - (time.monotonic() - tick)))
        except GameError as exc:
            self._hold = None
            await self.hub.send_admin({"type": "error", "message": str(exc)})

    async def set_tool(self, values) -> None:
        try:
            tool = Frame.from_list([float(v) for v in values])
        except (TypeError, ValueError) as exc:
            raise GameError("Das Tool braucht 7 Zahlen: x y z q1 q2 q3 q4.") from exc
        async with self._admin_motion(need_connection=False):
            self.db.set_setting("tool", tool.as_list())
            if self.robot.connected:
                await self.robot.apply_frame()
            self.robot.home_confirmed = False

    # ====================================================== admin: calibration
    def calibration_result(self) -> dict | None:
        pts = self.calib_points
        if not all(k in pts for k in (1, 2, 3)):
            return None
        try:
            result = frames.calibrate(pts[1], pts[2], pts[3], pts.get(4), *self._plate_size())
        except ValueError as exc:
            return {"error": str(exc)}
        spread = self._orientation_spread()
        if spread is not None and spread > ORIENTATION_TOLERANCE_DEG:
            result.warnings.append(
                f"Der Kopf wurde zwischen den Bohrungen um {spread:.1f}° gedreht. Alle Bohrungen "
                "mit derselben Kopfstellung anfahren (nur das Pad im Koordinatensystem Basis).")
        return {"wobj": [round(v, 5) for v in result.frame.as_list()],
                "orientation_spread_deg": None if spread is None else round(spread, 2),
                "distance_12": round(result.distance_12, 3), "distance_13": round(result.distance_13, 3),
                "skew_deg": round(result.skew_deg, 3),
                "expected_12": result.expected_12, "expected_13": result.expected_13,
                "check_error": None if result.check_error is None else round(result.check_error, 3),
                "warnings": result.warnings}

    def _orientation_spread(self) -> float | None:
        """Largest angle (°) between the head orientations of the measured holes."""
        quats = [self.calib_quats[k] for k in sorted(self.calib_points) if k in self.calib_quats]
        if len(quats) < 2:
            return None
        ref = quats[0]
        worst = 0.0
        for q in quats[1:]:
            dot = abs(sum(a * b for a, b in zip(ref, q)))
            worst = max(worst, math.degrees(2 * math.acos(min(1.0, dot))))
        return worst

    def _pen_quat(self) -> list[float] | None:
        """Mean head orientation of the measured holes (sign-aligned quaternion average)."""
        quats = [self.calib_quats[k] for k in sorted(self.calib_points) if k in self.calib_quats]
        if not quats:
            return None
        ref = quats[0]
        acc = [0.0, 0.0, 0.0, 0.0]
        for q in quats:
            sign = 1.0 if sum(a * b for a, b in zip(ref, q)) >= 0 else -1.0
            acc = [s + sign * v for s, v in zip(acc, q)]
        return [round(v, 6) for v in frames.quat_normalize(acc)]

    def _store_draft(self) -> None:
        self.db.set_setting("calib_draft", {str(k): v for k, v in self.calib_points.items()})
        self.db.set_setting("calib_draft_q", {str(k): v for k, v in self.calib_quats.items()})

    async def calib_save_point(self, index: int) -> list[float]:
        if index not in (1, 2, 3, 4):
            raise GameError("Es gibt nur die Bohrungen 1 bis 4.")
        async with self._admin_motion():
            if self.robot.frame_mode != "base":
                await self.robot.apply_frame("base")
            pose = await self.robot.read_pose()
            waiting = self._still_at_approach(pose.xyz)
            if waiting is not None:
                raise GameError(f"Der Stift steht noch {waiting['clearance']:g} mm vor der Bohrung. "
                                "Erst mit dem Pad ganz auf die Bohrung fahren, dann übernehmen.")
            self.calib_points[index] = [round(v, 3) for v in pose.xyz]
            self.calib_quats[index] = [round(v, 6) for v in frames.quat_normalize(pose.q)]
            self._store_draft()
            return self.calib_points[index]

    def calib_clear(self) -> None:
        self.last_hole_approach = None
        self.calib_points = {}
        self.calib_quats = {}
        self._store_draft()
        self.notify()

    async def calib_activate(self) -> None:
        result = self.calibration_result()
        if result is None:
            raise GameError("Es fehlen noch Messpunkte (Bohrung 1 bis 3).")
        if "error" in result:
            raise GameError(result["error"])
        async with self._admin_motion(need_connection=False):
            points = [self.calib_points.get(i) for i in (1, 2, 3, 4)]
            self.db.add_calibration(points, result["wobj"], self.db.get_setting("tool", DEFAULT_TOOL),
                                    pen_quat=self._pen_quat())
            self.robot.home_confirmed = False
            if self.robot.connected:
                await self.robot.apply_frame("plate")

    async def calib_remove(self) -> None:
        async with self._admin_motion(need_connection=False):
            self.db.clear_calibration()
            self.robot.home_confirmed = False
            if self.robot.connected:
                await self.robot.apply_frame()

    def _hole_estimate(self):
        if not self.calib_points:
            return None
        width, height = self._plate_size()
        try:
            return frames.estimate_holes(self.calib_points, width, height, self.robot.viewer_side())
        except (ValueError, ZeroDivisionError, FloatingPointError):
            return None

    def hole_predictions(self) -> dict[str, dict] | None:
        """Where the holes probably are (base coordinates), from the holes measured so far."""
        est = self._hole_estimate()
        if est is None:
            return None
        holes = frames.holes_plate(*self._plate_size())
        out = {}
        for index, (x, y) in holes.items():
            centre = est.hole(x, y)
            approach = centre + HOLE_APPROACH_CLEARANCE * est.towards_robot
            out[str(index)] = {"xyz": [round(float(v), 1) for v in centre],
                               "approach": [round(float(v), 1) for v in approach],
                               "measured": index in self.calib_points, "based_on": est.used}
        return out

    async def calib_goto_hole(self, index: int, clearance: float = HOLE_APPROACH_CLEARANCE) -> list[float]:
        """Drive to just in front of the (predicted) hole; the head is not turned.

        clearance 20 mm ("Hinfahren"): first straight away from the plate, then across.
        clearance 2 mm ("Näher ran"): straight towards the plate, the last bit is done by hand.
        """
        if index not in (1, 2, 3, 4):
            raise GameError("Es gibt nur die Bohrungen 1 bis 4.")
        if clearance not in (HOLE_APPROACH_CLEARANCE, HOLE_NEAR_CLEARANCE):
            raise GameError("Unbekannter Abstand.")
        est = self._hole_estimate()
        if est is None:
            raise GameError("Zuerst eine Bohrung anfahren und übernehmen, dann kann ich die anderen schätzen.")
        x, y = frames.holes_plate(*self._plate_size())[index]
        target = est.hole(x, y) + clearance * est.towards_robot
        async with self._admin_motion():
            await self.robot._prepare_admin("base")
            current = self.robot.commanded
            in_front = float(sum((c - o) * n for c, o, n in zip(current, est.origin, est.towards_robot)))
            if in_front < HOLE_APPROACH_CLEARANCE - 0.5:
                # 1) straight away from the plate first, so that the move across never touches it
                lift = HOLE_APPROACH_CLEARANCE - in_front
                await self.robot.move_to("base", tuple(float(c + lift * n)
                                                       for c, n in zip(current, est.towards_robot)))
            await self.robot.move_to("base", tuple(float(v) for v in target))
            self.last_hole_approach = {"index": index, "clearance": clearance,
                                       "target": [round(float(v), 2) for v in target]}
        return [round(float(v), 1) for v in target]

    def _still_at_approach(self, xyz) -> dict | None:
        last = self.last_hole_approach
        if last is not None and math.dist(xyz, last["target"]) < 0.5:
            return last
        return None

    async def sim_goto_hole(self, index: int) -> None:
        """Simulator only: put the virtual pen tip on a hole centre."""
        if not isinstance(self.robot.driver, SimDriver):
            raise GameError("Das geht nur im Simulator.")
        holes = frames.holes_plate(*self._plate_size())
        if index not in holes:
            raise GameError("Es gibt nur die Bohrungen 1 bis 4.")
        async with self._admin_motion():
            sim = self.config.sim
            plate = Frame.from_list([*sim.plate_origin, *sim.plate_quat])
            x, y = holes[index]
            self.robot.driver.teleport_base(plate.to_parent((x, y, 0.0)))
            await self.robot.apply_frame("base")
            self.robot.home_confirmed = False
            self.robot.at_home = False

    # ====================================================== admin: leaderboard profiles
    @staticmethod
    def _profile_name(raw: object) -> str:
        name = " ".join(str(raw or "").split())
        if not name:
            raise GameError("Bitte gib einen Namen für das Profil ein.")
        if len(name) > PROFILE_NAME_MAX:
            raise GameError(f"Der Name darf höchstens {PROFILE_NAME_MAX} Zeichen haben.")
        return name

    def _require_no_visitor_run(self) -> None:
        if self.run is not None:
            raise GameError("Während eines Laufs geht das nicht. Warte, bis der Roboter zu Hause ist.")

    def create_profile(self, name: object, activate: bool = False) -> int:
        profile_id = self.db.add_profile(self._profile_name(name))
        if activate:
            self.activate_profile(profile_id)
        self.notify()
        return profile_id

    def activate_profile(self, profile_id: int) -> None:
        if self.db.profile(profile_id) is None:
            raise GameError("Dieses Profil gibt es nicht.")
        self._require_no_visitor_run()
        self.db.activate_profile(profile_id)
        log.info("Bestenlisten-Profil %d aktiviert", profile_id)
        self.notify()

    def rename_profile(self, profile_id: int, name: object) -> None:
        if self.db.profile(profile_id) is None:
            raise GameError("Dieses Profil gibt es nicht.")
        self.db.rename_profile(profile_id, self._profile_name(name))
        self.notify()

    def delete_profile(self, profile_id: int) -> None:
        profile = self.db.profile(profile_id)
        if profile is None:
            raise GameError("Dieses Profil gibt es nicht.")
        if profile["active"]:
            raise GameError("Das aktive Profil kann nicht gelöscht werden. Aktiviere zuerst ein anderes.")
        self.db.delete_profile(profile_id)
        self.notify()

    def stats(self) -> dict:
        """Data for the statistics page: every run of the active profile on the active labyrinth."""
        lab_id = self.lab.id if self.lab else None
        runs = self.db.stats_runs(lab_id) if lab_id is not None else []
        return {"profile": self.db.active_profile(), "year": date.today().year,
                "runs": [{"id": r["id"], "name": r["name"], "birth_year": r["birth_year"],
                          "time_ms": r["time_ms"], "status": r["status"], "mode": r["speed_mode"],
                          "at": r["created_at"], "replay": bool(r["replay"])} for r in runs],
                "boards": self.board.boards(lab_id), "robot_best_ms": self.board.robot_best(lab_id),
                "speeds": self.speeds()}

    # ====================================================== admin: leaderboard
    def delete_run(self, run_id: int) -> None:
        self.db.delete_run(run_id)
        self.notify()

    def reset_leaderboard(self) -> None:
        if self.lab is not None:
            self.db.reset_runs(self.lab.id)
        self.notify()

    def reset_robot_best(self) -> None:
        if self.lab is not None:
            self.db.reset_robot_runs(self.lab.id)
        self.notify()

    # ================================================================ snapshot
    def snapshot(self) -> dict:
        state = self.sm.state
        now_ns = time.monotonic_ns()
        run = None
        if self.run is not None:
            run = {"kind": self.run["kind"], "name": self.run["name"],
                   "running": bool(self.timer and self.timer.running),
                   "elapsed_ms": self.timer.elapsed_ms(now_ns) if self.timer else 0}
        position = self.robot.live_position() if self.robot.frame_mode == "plate" else None
        labyrinth_id = self.lab.id if self.lab else None
        shown_mode = self.run.get("speed_mode", "normal") if self.run else self.speed_mode
        return {
            "type": "state", "state": state.value, "server_ms": now_ns // 1_000_000, "run": run,
            "countdown_ms": (max(0, round((self.countdown_end - time.monotonic()) * 1000))
                             if self.countdown_end is not None and state == S.COUNTDOWN else None),
            "robot": {"connected": self.robot.connected, "driver": self.robot.driver.name,
                      "pos": [round(position[0], 2), round(position[1], 2)] if position else None},
            "leaderboard": self.board.top(labyrinth_id, shown_mode),
            "boards": self.board.boards(labyrinth_id),
            "robot_best_ms": self.board.robot_best(labyrinth_id),
            "auto_request": ({"age_ms": round((time.monotonic() - self.auto_request_at) * 1000)}
                             if self.auto_request_at is not None and state == S.AUTO_REQUESTED else None),
            "result": self.result, "auto_result": self.auto_result, "notice": self.notice,
            "wall_hit": self.wall_hit,
            "speed_mode": self.run.get("speed_mode", "normal") if self.run else self.speed_mode,
            "speeds": self.speeds(),
            "sound": {"on": self.settings["sound"] == "on", "volume": self.settings["sound_volume"]},
            "can_start": self.why_not() is None, "labyrinth_rev": self.lab_rev,
            "display": {"theme": self.settings["visitor_theme"], "rotate_s": self.settings["board_rotate_s"]},
            "profile": self.db.active_profile(), "runs_rev": self.db.runs_revision(),
            "replay": self.replay_public(),
        }

    def admin_snapshot(self) -> dict:
        data = self.snapshot()
        robot, calibration = self.robot, self.robot.calibration()
        position = robot.live_position()
        info = robot.info
        data["admin"] = {
            "home_confirmed": robot.home_confirmed, "at_home": robot.at_home,
            "frame": robot.frame_mode, "busy": self._admin_lock.locked(),
            "pose": [round(v, 2) for v in position] if position else None,
            "latency_ms": round(robot.driver.latency_ms, 1), "cycle_ms": round(self.cycle_ms, 1),
            "info": ({"serial": info.serial, "robotware": info.robotware, "robot_type": info.robot_type}
                     if info else None),
            "last_error": robot.last_error, "message": self.message,
            "why_not": self.why_not(), "readiness": self.readiness(), "paused": self.paused,
            "viewer_side": robot.viewer_side(), "pen_taught": robot.measured_pen_quat() is not None,
            "logger": robot.driver.has_actual_position,
            "timing_effective": self.effective_timing_method(),
            "calibration": calibration, "calib_points": {str(k): v for k, v in self.calib_points.items()},
            "calib_result": self.calibration_result(),
            "hole_predictions": self.hole_predictions(), "hole_clearance": HOLE_APPROACH_CLEARANCE,
            "hole_near_clearance": HOLE_NEAR_CLEARANCE,
            "hole_waiting": (dict(self.last_hole_approach) if self.last_hole_approach and robot.commanded
                             and self._still_at_approach(robot.commanded) else None),
            "tool": self.db.get_setting("tool", DEFAULT_TOOL), "home_joints": robot.home_joints,
            "settings": self.settings.all(),
            "profiles": self.db.profiles(),
            "active_labyrinth": ({"id": self.lab.id, "name": self.lab.name, "ready": self.lab.ready,
                                  "size": [self.lab.geometry.width, self.lab.geometry.height]}
                                 if self.lab else None),
            "run_detail": ({"name": self.run["name"], "birth_year": self.run["birth_year"]}
                           if self.run else None),
        }
        return data

    async def _broadcast_loop(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._dirty.wait(), 1.0)
            except asyncio.TimeoutError:
                pass
            self._dirty.clear()
            try:
                await self.hub.send_public(self.snapshot())
                await self.hub.send_admin(self.admin_snapshot())
            except Exception:
                log.exception("Fehler beim Senden des Zustands")
            await asyncio.sleep(0.03)

    async def _position_loop(self) -> None:
        """Pen position for the live map, at most 20 Hz and only when it changed."""
        last = None
        while True:
            await asyncio.sleep(0.05)
            position = self.robot.live_position() if self.robot.connected else None
            current = (self.robot.frame_mode, position)
            if current != last:
                last = current
                try:
                    await self.hub.send_admin({
                        "type": "pos", "frame": self.robot.frame_mode,
                        "pos": [round(v, 2) for v in position] if position else None})
                except Exception:
                    log.exception("Fehler beim Senden der Position")
