"""TCP client for the RAPID module SERVER.mod (open_abb protocol, CLAUDE.md §4.2).

Strictly request → response: a new message is only sent after the answer to
the previous one has been read, so the 80 ms pause of the original abb.py is
not needed. All methods block; the drivers run them in a worker thread.
"""
from __future__ import annotations

import select
import socket
import threading
import time
from collections import deque
from typing import Sequence

ZONES: dict[str, tuple[float, float, float]] = {
    "z0": (0.3, 0.3, 0.03), "z1": (1, 1, 0.1), "z5": (5, 8, 0.8), "z10": (10, 15, 1.5),
    "z15": (15, 23, 2.3), "z20": (20, 30, 3), "z30": (30, 45, 4.5), "z50": (50, 75, 7.5),
    "z100": (100, 150, 15), "z200": (200, 300, 30),
}


class ProtocolError(Exception):
    """Base class for everything that can go wrong while talking to the robot."""


class ConnectionLost(ProtocolError):
    """Socket closed, timed out or not connected."""


class CommandRejected(ProtocolError):
    """The server answered with SERVER_BAD_MSG (ok = 0)."""


class BadResponse(ProtocolError):
    """The answer does not belong to the request."""


def zone_radius(zone: str) -> float:
    return 0.0 if zone == "fine" else ZONES[zone][0]


def format_pose(xyz: Sequence[float], quat: Sequence[float]) -> str:
    """Seven parameters formatted exactly like abb.py (`+08.1f` / `+08.5f`)."""
    if len(xyz) != 3 or len(quat) != 4:
        raise ValueError("Pose braucht 3 Koordinaten und 4 Quaternion-Werte")
    parts = [format(float(v), "+08.1f") for v in xyz] + [format(float(q), "+08.5f") for q in quat]
    return " ".join(parts)


def format_joints(joints: Sequence[float]) -> str:
    if len(joints) != 6:
        raise ValueError("Es werden genau 6 Gelenkwinkel erwartet")
    return " ".join(format(float(j), "+08.2f") for j in joints)


def format_speed(v_tcp: float, v_ori: float, v_leax: float = 50.0, v_reax: float = 50.0) -> str:
    return " ".join([format(v_tcp, "+08.1f"), format(v_ori, "+08.2f"),
                     format(v_leax, "+08.1f"), format(v_reax, "+08.2f")])


def format_zone(zone: str) -> str:
    fine = zone == "fine"
    values = (0.0, 0.0, 0.0) if fine else ZONES[zone]
    return " ".join([str(int(fine))] + [format(v, "+08.4f") for v in values])


def build_message(code: int, body: str = "") -> bytes:
    """`"<2-digit code> <params> #"` – the terminating `#` is required by ParseMsg."""
    text = f"{code:02d} {body} #" if body else f"{code:02d} #"
    if len(text) > 80:      # RAPID strings hold at most 80 characters
        raise ValueError(f"Nachricht zu lang für RAPID ({len(text)} Zeichen)")
    return text.encode("ascii")


class AbbClient:
    def __init__(self, ip: str = "192.168.0.30", port: int = 5000,
                 connect_timeout: float = 2.5, timeout: float = 5.0):
        self.ip, self.port = ip, port
        self.connect_timeout, self.timeout = connect_timeout, timeout
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self.last_latency: float = 0.0             # seconds, last command
        self.latencies: deque[float] = deque(maxlen=200)
        self.last_traffic: float = 0.0             # time.monotonic() of the last answer

    # ------------------------------------------------------------- connection
    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> None:
        self.close(send_goodbye=False)
        try:
            sock = socket.create_connection((self.ip, self.port), timeout=self.connect_timeout)
        except OSError as exc:
            raise ConnectionLost(f"Keine Verbindung zu {self.ip}:{self.port} ({exc})") from exc
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        self.last_traffic = time.monotonic()

    def close(self, send_goodbye: bool = True) -> None:
        sock, self._sock = self._sock, None
        if sock is None:
            return
        try:
            if send_goodbye:
                sock.settimeout(0.5)
                sock.sendall(build_message(99))   # server closes and waits for a new client
        except OSError:
            pass
        finally:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def _drop(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    # ---------------------------------------------------------------- request
    def request(self, code: int, body: str = "", timeout: float | None = None) -> list[str]:
        """Send one command and return the tokens after `<code> <ok>`."""
        message = build_message(code, body)
        with self._lock:
            sock = self._sock
            if sock is None:
                raise ConnectionLost("Nicht verbunden")
            started = time.perf_counter()
            try:
                sock.settimeout(timeout if timeout is not None else self.timeout)
                sock.sendall(message)
                data = sock.recv(4096)
                if not data:
                    self._drop()
                    raise ConnectionLost("Der Roboter hat die Verbindung geschlossen")
                # Answers have no terminator. They are one small packet; pick up
                # a possible second fragment without waiting noticeably.
                while select.select([sock], [], [], 0.002)[0]:
                    more = sock.recv(4096)
                    if not more:
                        break
                    data += more
            except socket.timeout as exc:
                self._drop()
                raise ConnectionLost(f"Zeitüberschreitung bei Befehl {code:02d}") from exc
            except OSError as exc:
                self._drop()
                raise ConnectionLost(f"Verbindungsfehler bei Befehl {code:02d} ({exc})") from exc
            self.last_latency = time.perf_counter() - started
            self.latencies.append(self.last_latency)
            self.last_traffic = time.monotonic()

        tokens = data.decode("ascii", errors="replace").split()
        if len(tokens) < 2:
            raise BadResponse(f"Unvollständige Antwort auf Befehl {code:02d}: {data!r}")
        try:
            answered, ok = int(float(tokens[0])), int(float(tokens[1]))
        except ValueError as exc:
            raise BadResponse(f"Unlesbare Antwort auf Befehl {code:02d}: {data!r}") from exc
        if answered != code:
            raise BadResponse(f"Antwort {answered} passt nicht zu Befehl {code:02d}")
        if ok != 1:
            raise CommandRejected(f"Der Roboter hat Befehl {code:02d} abgelehnt")
        return tokens[2:]

    # --------------------------------------------------------------- commands
    def ping(self) -> float:
        self.request(0)
        return self.last_latency

    def move_cartesian(self, xyz, quat, timeout: float | None = None) -> None:
        self.request(1, format_pose(xyz, quat), timeout)

    def move_joints(self, joints, timeout: float | None = None) -> None:
        self.request(2, format_joints(joints), timeout)

    def get_cartesian(self) -> tuple[list[float], list[float]]:
        values = [float(t) for t in self.request(3)]
        if len(values) != 7:
            raise BadResponse("Pose mit falscher Anzahl Werte")
        return values[:3], values[3:]

    def get_joints(self) -> list[float]:
        values = [float(t) for t in self.request(4)]
        if len(values) != 6:
            raise BadResponse("Gelenkwinkel mit falscher Anzahl Werte")
        return values

    def set_tool(self, xyz, quat) -> None:
        self.request(6, format_pose(xyz, quat))

    def set_workobject(self, xyz, quat) -> None:
        self.request(7, format_pose(xyz, quat))

    def set_speed(self, v_tcp: float, v_ori: float = 50.0) -> None:
        self.request(8, format_speed(v_tcp, v_ori))

    def set_zone(self, zone: str) -> None:
        self.request(9, format_zone(zone))

    def buffer_add(self, xyz, quat) -> None:
        self.request(30, format_pose(xyz, quat))

    def buffer_clear(self) -> None:
        self.request(31)

    def buffer_len(self) -> int:
        return int(float(self.request(32)[0]))

    def buffer_execute(self, timeout: float | None = None) -> None:
        self.request(33, timeout=timeout)

    def robot_info(self) -> list[str]:
        """[serial number, RobotWare version, robot type]."""
        text = " ".join(self.request(98))
        return [part.strip() for part in text.split("*")]


class LoggerStream:
    """Reads the pose stream of LOGGER.mod (port 5001) in a background thread.

    Message: ``# 0 <date> <time> <clock> x y z q1 q2 q3 q4`` (0 = pose, 1 = joints).
    """

    def __init__(self, ip: str, port: int = 5001, connect_timeout: float = 1.0):
        self.ip, self.port, self.connect_timeout = ip, port, connect_timeout
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.pose: tuple[float, float, float] | None = None
        self.pose_time: float = 0.0
        self.running = False

    def start(self) -> bool:
        try:
            sock = socket.create_connection((self.ip, self.port), timeout=self.connect_timeout)
        except OSError:
            return False
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(target=self._run, args=(sock,), daemon=True, name="abb-logger")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        self.running = False

    def fresh_pose(self, max_age: float = 0.5) -> tuple[float, float, float] | None:
        if self.pose is not None and time.monotonic() - self.pose_time <= max_age:
            return self.pose
        return None

    @staticmethod
    def parse(chunk: str) -> list[tuple[int, list[float]]]:
        out = []
        for part in chunk.split("#"):
            tokens = part.split()
            if len(tokens) < 5:
                continue
            try:
                kind = int(tokens[0])
                values = [float(t) for t in tokens[4:]]
            except ValueError:
                continue
            out.append((kind, values))
        return out

    def _run(self, sock: socket.socket) -> None:
        sock.settimeout(1.0)
        try:
            while not self._stop.is_set():
                try:
                    data = sock.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    break
                for kind, values in self.parse(data.decode("ascii", errors="replace")):
                    if kind == 0 and len(values) >= 3:
                        self.pose = (values[0], values[1], values[2])
                        self.pose_time = time.monotonic()
        except OSError:
            pass
        finally:
            self.running = False
            try:
                sock.close()
            except OSError:
                pass
