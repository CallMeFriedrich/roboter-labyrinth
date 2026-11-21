"""Fake controller: a TCP server that behaves like SERVER.mod (CLAUDE.md §12).

Start it on the laptop to test the standard driver without a robot:

    .venv\\Scripts\\python tools\\fake_controller.py --port 5000

Then set the robot IP in config.toml to 127.0.0.1 and choose the driver
"Standard" in the admin panel.

Implemented: codes 0–9, 30–36, 98, 99 with the semantics of SERVER.mod:
answers only after the simulated motion, zone behaviour, single-threaded
command loop, SERVER_BAD_MSG on a wrong parameter count. Optional artificial
latency, random connection drops and a LOGGER.mod stream on a second port.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.geometry.frames import Frame, quat_normalize  # noqa: E402
from app.robot.motion_model import MotionModel  # noqa: E402

for _stream in (sys.stdout, sys.stderr):      # Windows consoles default to cp1252
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

MAX_BUFFER = 512


def num_to_str(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


class FakeController:
    def __init__(self, host: str = "127.0.0.1", port: int = 5000, latency_ms: float = 0.0,
                 drop_probability: float = 0.0, time_scale: float = 1.0,
                 logger_port: int | None = None, acceleration: float = 1000.0):
        self.host, self.port = host, port
        self.latency_ms = latency_ms
        self.drop_probability = drop_probability
        self.time_scale = time_scale
        self.logger_port = logger_port
        self.model = MotionModel(acceleration, time_scale=time_scale)
        self.speed = 100.0
        self.zone_fine = False
        self.zone_radius = 0.3
        self.buffer: list[tuple[list[float], list[float], float]] = []
        self.circ_point: list[float] | None = None
        self.last_code = 0
        self.commands: list[str] = []         # log of received messages (tests)
        self.drop_next = False                # test hook: close the socket on the next command
        self._server: asyncio.AbstractServer | None = None
        self._logger_server: asyncio.AbstractServer | None = None
        self._busy = asyncio.Lock()           # one client at a time, like the RAPID task
        self._writers: set[asyncio.StreamWriter] = set()

    def initialize(self) -> None:
        """PROC Initialize: default tool, work object, speed and zone z0."""
        self.model.set_tool(Frame())
        self.model.set_wobj(Frame())
        self.speed, self.zone_fine, self.zone_radius = 100.0, False, 0.3

    async def start(self) -> None:
        self.initialize()
        self._server = await asyncio.start_server(self._serve, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]
        if self.logger_port is not None:
            self._logger_server = await asyncio.start_server(self._serve_logger, self.host, self.logger_port)
            self.logger_port = self._logger_server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        for server in (self._server, self._logger_server):
            if server is not None:
                server.close()
        for writer in list(self._writers):
            writer.close()
        for server in (self._server, self._logger_server):
            if server is not None:
                try:
                    await asyncio.wait_for(server.wait_closed(), 1.0)
                except (asyncio.TimeoutError, Exception):
                    pass
        self._server = self._logger_server = None

    # ---------------------------------------------------------------- parsing
    def parse(self, text: str) -> tuple[int | None, list[float] | None]:
        """Mirror of PROC ParseMsg: returns (code, params) or (None, None) if corrupt."""
        end = text.find("#")
        if end < 0:
            return None, None
        tokens = text[:end].split()
        if not tokens:
            return None, None
        try:
            code = int(float(tokens[0]))
            params = [float(t) for t in tokens[1:]]
        except ValueError:
            return None, None
        if len(params) > 10:
            return None, None
        return code, params

    # ----------------------------------------------------------------- server
    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        try:
            async with self._busy:
                while True:
                    data = await reader.read(4096)
                    if not data:
                        break
                    text = data.decode("ascii", errors="replace")
                    self.commands.append(text)
                    if self.drop_next or (self.drop_probability and random.random() < self.drop_probability):
                        self.drop_next = False
                        break
                    if self.latency_ms:
                        await asyncio.sleep(self.latency_ms / 1000.0)
                    # Two messages glued together: like RAPID, only the first one counts.
                    code, params = self.parse(text)
                    if code == 99 and params == []:
                        break
                    answer = await self._execute(code, params)
                    writer.write(answer.encode("ascii"))
                    await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()

    async def _execute(self, code: int | None, params: list[float] | None) -> str:
        if code is None or params is None:
            return f"{self.last_code} 0 "
        self.last_code = code
        n = len(params)
        ok, add = 1, ""
        m = self.model
        radius = 0.0 if self.zone_fine else self.zone_radius

        if code == 0:
            ok = int(n == 0)
        elif code == 1:
            if n == 7:
                await m.move_linear(params[:3], quat_normalize(params[3:]), self.speed, radius)
            else:
                ok = 0
        elif code == 2:
            if n == 6:
                await m.move_joints(params, self.speed)
            else:
                ok = 0
        elif code == 3:
            if n == 0:
                xyz, quat = m.pose_in_wobj()
                add = " ".join([num_to_str(v, 2) for v in xyz] + [num_to_str(q, 3) for q in quat])
            else:
                ok = 0
        elif code == 4:
            if n == 0:
                add = " ".join(num_to_str(j, 2) for j in m.get_joints())
            else:
                ok = 0
        elif code == 5:
            add, ok = (" ".join(["0.00"] * 6), 1) if n == 0 else ("", 0)
        elif code == 6:
            if n == 7:
                m.set_tool(Frame(tuple(params[:3]), quat_normalize(params[3:])))
            else:
                ok = 0
        elif code == 7:
            if n == 7:
                m.set_wobj(Frame(tuple(params[:3]), quat_normalize(params[3:])))
            else:
                ok = 0
        elif code == 8:
            if n in (2, 4):
                self.speed = params[0]
            else:
                ok = 0
        elif code == 9:
            if n == 4:
                self.zone_fine = params[0] == 1
                self.zone_radius = 0.0 if self.zone_fine else params[1]
            else:
                ok = 0
        elif code == 30:
            if n == 7:
                if len(self.buffer) < MAX_BUFFER:
                    self.buffer.append((params[:3], params[3:], self.speed))
            else:
                ok = 0
        elif code == 31:
            if n == 0:
                self.buffer.clear()
            else:
                ok = 0
        elif code == 32:
            add, ok = (num_to_str(len(self.buffer), 2), 1) if n == 0 else ("", 0)
        elif code == 33:
            if n == 0:
                for i, (xyz, quat, speed) in enumerate(self.buffer):
                    last = i == len(self.buffer) - 1
                    await m.move_linear(xyz, quat_normalize(quat), speed, 0.0 if last else radius)
            else:
                ok = 0
        elif code == 34:
            ok = int(n == 6)
        elif code == 35:
            if n == 7:
                self.circ_point = params
            else:
                ok = 0
        elif code == 36:
            if n == 7 and self.circ_point is not None:
                # Approximation of MoveC: via the circle point, then to the target.
                await m.move_linear(self.circ_point[:3], quat_normalize(self.circ_point[3:]), self.speed, 1.0)
                await m.move_linear(params[:3], quat_normalize(params[3:]), self.speed, radius)
            else:
                ok = 0
        elif code == 98:
            add, ok = ("120-FAKE*ROBOTWARE_6.00.0000*IRB 120-3/0.6", 1) if n == 0 else ("", 0)
        else:
            ok = 0
        return f"{code} {ok} {add}"

    # ----------------------------------------------------------------- logger
    async def _serve_logger(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        started = time.monotonic()
        stamp = datetime.now()
        try:
            while True:
                xyz = self.model.position_in_wobj_now()
                quat = self.model.wobj.quat_to_local(self.model.quat_base)
                clock = num_to_str(time.monotonic() - started, 2)
                head = f"{stamp:%Y-%m-%d} {stamp:%H:%M:%S} {clock} "
                pose = "# 0 " + head + " ".join([num_to_str(v, 1) for v in xyz] + [num_to_str(q, 3) for q in quat])
                writer.write(pose.encode("ascii"))
                await writer.drain()
                await asyncio.sleep(0.01)
                joints = "# 1 " + head + " ".join(num_to_str(j, 2) for j in self.model.joints)
                writer.write(joints.encode("ascii"))
                await writer.drain()
                await asyncio.sleep(0.01)
        except (ConnectionError, OSError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Fake-Controller, der SERVER.mod nachbildet")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--logger-port", type=int, default=5001, help="0 = kein LOGGER-Stream")
    parser.add_argument("--latency-ms", type=float, default=5.0)
    parser.add_argument("--drop-probability", type=float, default=0.0,
                        help="Wahrscheinlichkeit pro Befehl für einen Verbindungsabbruch")
    args = parser.parse_args()
    controller = FakeController(args.host, args.port, args.latency_ms, args.drop_probability,
                                logger_port=args.logger_port or None)
    await controller.start()
    print(f"Fake-Controller läuft auf {args.host}:{controller.port}"
          + (f", LOGGER auf Port {controller.logger_port}" if controller.logger_port else "")
          + ". Beenden mit Strg+C.")
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
