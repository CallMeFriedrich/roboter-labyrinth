r"""Diagnose für den Robotertermin am 18.11. (CLAUDE.md §13).

Interaktiv, mit Bestätigung vor jeder Bewegung. Schreibt ein Protokoll
`diagnose_YYYYMMDD_HHMM.json` und `.md` in den Ordner `data/diagnose/`.

    .venv\Scripts\python tools\diagnose.py                 (echter Roboter, 192.168.0.30)
    .venv\Scripts\python tools\diagnose.py --ip 127.0.0.1  (gegen tools\fake_controller.py)
    .venv\Scripts\python tools\diagnose.py --yes --quick   (ohne Rückfragen, kurzer Test – nur Fake!)

Sicherheit: Jede Bewegung wird vorher angekündigt. Der Arbeitsraum muss frei
sein, eine zweite Person steht am Not-Halt. Abbruch jederzeit mit Strg+C –
eine bereits gesendete Bewegung fährt der Roboter aber zu Ende.
"""
from __future__ import annotations

import argparse
import json
import socket
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.robot.protocol import AbbClient, LoggerStream, ProtocolError  # noqa: E402
from app.settings import ROOT  # noqa: E402

for _stream in (sys.stdout, sys.stderr):      # Windows consoles default to cp1252
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

START_JOINTS = [0, 45, 0, 0, -45, 0]
PEN_QUAT = [0.707, 0, 0.707, 0]          # tool z horizontal towards +x (from the old test scripts)
JOINT_LIMITS = [(-165, 165), (-110, 110), (-110, 70), (-160, 160), (-120, 120), (-400, 400)]
CHECKLIST = [
    "FlexPendant: Option „PC Interface“ vorhanden?",
    "FlexPendant: Option „Multitasking“ vorhanden?",
    "FlexPendant: Option „EGM“ (Externally Guided Motion) vorhanden?",
    "RobotStudio-Zugang mit Schreibrecht auf den Controller möglich?",
    "Not-Halt-Ablauf geübt (quittieren, Motoren an, PP to Main, Play)?",
    "Flanschmaße geprüft (Ø 40, 4× M5 auf Ø 31,5, Passstift Ø 5)?",
    "Fotos von Aufbau, Flansch und FlexPendant-Optionen gemacht?",
    "Besucherseite festgelegt (Roboterseite oder gegenüber)?",
    "Lage der Platte gemessen (Abstand, Höhe)?",
]


class Report:
    def __init__(self, args: argparse.Namespace):
        self.started = datetime.now()
        self.data: dict = {"started": self.started.isoformat(timespec="seconds"),
                           "target": f"{args.ip}:{args.port}", "steps": {}}
        self.lines: list[str] = [f"# Diagnose {self.started:%d.%m.%Y %H:%M}", "",
                                 f"Ziel: `{args.ip}:{args.port}`", ""]

    def section(self, key: str, title: str, value, text: list[str]) -> None:
        self.data["steps"][key] = value
        self.lines += [f"## {title}", "", *text, ""]
        print()
        print(f"== {title}")
        for line in text:
            print("   " + line)

    def save(self) -> Path:
        folder = ROOT / "data" / "diagnose"
        folder.mkdir(parents=True, exist_ok=True)
        stem = folder / f"diagnose_{self.started:%Y%m%d_%H%M}"
        stem.with_suffix(".json").write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        stem.with_suffix(".md").write_text("\n".join(self.lines), encoding="utf-8")
        return stem


def ask(question: str, auto_yes: bool) -> bool:
    if auto_yes:
        print(f"   {question} [automatisch ja]")
        return True
    answer = input(f"   {question} [j/N] ").strip().lower()
    return answer in ("j", "ja", "y", "yes")


def stats(values_ms: list[float]) -> dict:
    ordered = sorted(values_ms)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    return {"n": len(ordered), "min": round(ordered[0], 2), "median": round(statistics.median(ordered), 2),
            "p95": round(p95, 2), "max": round(ordered[-1], 2)}


def fmt(s: dict) -> str:
    return f"min {s['min']} · Median {s['median']} · p95 {s['p95']} · max {s['max']} ms (n = {s['n']})"


# ----------------------------------------------------------------------- steps
def step_ping(robot: AbbClient, report: Report) -> None:
    values = [robot.ping() * 1000 for _ in range(100)]
    s = stats(values)
    report.section("ping", "1 · Verbindung und Ping", s, [f"100 Pings: {fmt(s)}"])


def step_info(robot: AbbClient, report: Report) -> None:
    info = robot.robot_info()
    info = (info + ["", "", ""])[:3]
    report.section("info", "2 · Roboter-Info", {"serial": info[0], "robotware": info[1], "type": info[2]},
                   [f"Seriennummer: {info[0]}", f"RobotWare: {info[1]}", f"Robotertyp: {info[2]}"])


def step_pose(robot: AbbClient, report: Report) -> None:
    xyz, quat = robot.get_cartesian()
    joints = robot.get_joints()
    report.section("pose", "3 · Aktuelle Pose und Gelenke", {"xyz": xyz, "quat": quat, "joints": joints},
                   [f"Pose: {xyz} mm, Quaternion {quat}", f"Gelenke: {joints} °"])


def step_logger(args: argparse.Namespace, report: Report) -> None:
    result: dict = {"reachable": False}
    text = []
    try:
        sock = socket.create_connection((args.ip, args.logger_port), timeout=2.0)
    except OSError as exc:
        text.append(f"LOGGER auf Port {args.logger_port} antwortet nicht ({exc}).")
        text.append("→ Zeitmessung im Auto-Lauf über „Halt an Linien“.")
    else:
        sock.settimeout(0.5)
        chunks, end = [], time.monotonic() + 2.0
        while time.monotonic() < end:
            try:
                data = sock.recv(4096)
            except socket.timeout:
                continue
            if not data:
                break
            chunks.append(data.decode("ascii", errors="replace"))
        sock.close()
        parsed = LoggerStream.parse("".join(chunks))
        poses = [values for kind, values in parsed if kind == 0 and len(values) >= 7]
        joints = [values for kind, values in parsed if kind == 1 and len(values) >= 6]
        result = {"reachable": True, "pose_messages": len(poses), "joint_messages": len(joints),
                  "rate_hz": round(len(poses) / 2.0, 1), "sample": "".join(chunks)[:160]}
        text.append(f"LOGGER läuft: {len(poses)} Posen und {len(joints)} Gelenk-Nachrichten in 2 s "
                    f"(≈ {result['rate_hz']} Hz).")
        text.append("Format in Ordnung." if poses else "Achtung: Format wurde nicht erkannt.")
    report.section("logger", "4 · LOGGER (Port 5001)", result, text)


def to_start_pose(robot: AbbClient) -> tuple[list[float], list[float]]:
    robot.set_speed(50.0)
    robot.set_zone("fine")
    robot.move_joints(START_JOINTS, 60.0)
    return robot.get_cartesian()


def step_motion(robot: AbbClient, report: Report, args: argparse.Namespace) -> None:
    print()
    print("== 5 · Bewegungstest")
    print(f"   Der Roboter fährt auf die Startpose {START_JOINTS} und macht dann kleine Schritte")
    print("   in ±y und ±z (höchstens 100 mm vom Startpunkt), in freier Luft vor dem Roboter.")
    if not ask("Arbeitsraum frei, Person am Not-Halt? Bewegungstest starten?", args.yes):
        report.section("motion", "5 · Bewegungstest", {"skipped": True}, ["Übersprungen."])
        return
    origin, quat = to_start_pose(robot)
    steps_mm = [2] if args.quick else [1, 2, 3, 5]
    speeds = [50] if args.quick else [30, 50, 100]
    zones = ["z1"] if args.quick else ["z0", "z1", "z5"]
    count = 5 if args.quick else 20
    rows, results = [], []
    try:
        for zone in zones:
            for speed in speeds:
                for step in steps_mm:
                    robot.set_zone("fine")
                    robot.set_speed(20.0)
                    robot.move_cartesian(origin, quat, 30.0)       # back to the start point, slowly
                    robot.set_speed(float(speed))
                    robot.set_zone(zone)
                    latencies = []
                    position = list(origin)
                    # +y, +z, −y, −z in equal parts: a small square, ends where it began.
                    for i in range(count):
                        axis, sign = [(1, 1), (2, 1), (1, -1), (2, -1)][i * 4 // count]
                        position[axis] += sign * step
                        robot.move_cartesian(position, quat, 10.0)
                        latencies.append(robot.last_latency * 1000)
                    before, _ = robot.get_cartesian()
                    time.sleep(1.0)
                    after, _ = robot.get_cartesian()
                    overrun = max(abs(a - b) for a, b in zip(before, after))
                    s = stats(latencies)
                    ideal = step / speed * 1000
                    results.append({"zone": zone, "speed": speed, "step": step, "latency_ms": s,
                                    "ideal_ms": round(ideal, 1), "overrun_mm": round(overrun, 2),
                                    "effective_speed": round(step / (s["median"] / 1000), 1)})
                    rows.append(f"| {zone} | {speed} | {step} | {s['median']} | {s['p95']} | "
                                f"{ideal:.0f} | {results[-1]['effective_speed']} | {overrun:.2f} |")
                    print(f"   {zone} {speed:>3} mm/s {step} mm: Median {s['median']} ms, "
                          f"effektiv {results[-1]['effective_speed']} mm/s, Nachlauf {overrun:.2f} mm")
    finally:
        robot.set_zone("fine")
        robot.set_speed(20.0)
        robot.move_cartesian(origin, quat, 30.0)
    report.section("motion", "5 · Bewegungstest", results, [
        "Antwortzeit pro `MoveL`-Befehl, Nachlauf = Bewegung in der Sekunde nach dem letzten Befehl.", "",
        "| Zone | Speed mm/s | Schritt mm | Median ms | p95 ms | ideal ms | effektiv mm/s | Nachlauf mm |",
        "|---|---|---|---|---|---|---|---|", *rows])


def step_buffer(robot: AbbClient, report: Report, args: argparse.Namespace) -> None:
    print()
    print("== 6 · Puffer-Test: 10 Punkte auf einer 45-mm-Strecke in y, hin und zurück.")
    if not ask("Puffer-Test starten?", args.yes):
        report.section("buffer", "6 · Puffer-Test", {"skipped": True}, ["Übersprungen."])
        return
    origin, quat = to_start_pose(robot)
    robot.set_speed(50.0)
    robot.buffer_clear()
    points = [[origin[0], origin[1] + 9 * i, origin[2]] for i in (1, 2, 3, 4, 5, 4, 3, 2, 1, 0)]
    for point in points:
        robot.buffer_add(point, quat)
    length = robot.buffer_len()
    robot.set_zone("z1")
    started = time.monotonic()
    robot.buffer_execute(60.0)
    duration = time.monotonic() - started
    robot.buffer_clear()
    robot.set_zone("fine")
    end, _ = robot.get_cartesian()
    error = max(abs(a - b) for a, b in zip(end, origin))
    report.section("buffer", "6 · Puffer-Test (Codes 30–33)",
                   {"points": length, "duration_s": round(duration, 2), "end_error_mm": round(error, 2)},
                   [f"{length} von 10 Punkten im Puffer, Ausführung {duration:.2f} s für 90 mm bei 50 mm/s "
                    f"(ideal 1,8 s).", f"Endposition weicht {error:.2f} mm vom Start ab."])


def step_reach(robot: AbbClient, report: Report, args: argparse.Namespace) -> None:
    print()
    print("== 7 · Reichweiten-Test für die 400-mm-Platte")
    print("   Senkrechte Ebene y–z vor dem Roboter. Angefahren werden die 4 Ecken ±185 mm")
    print("   mit Stiftausrichtung, langsam (30 mm/s).")
    if args.yes:
        x, cy, cz = args.plate_x, 0.0, args.plate_z
    else:
        try:
            x = float(input(f"   Abstand der Ebene x in mm [{args.plate_x}]: ") or args.plate_x)
            cy = float(input("   Plattenmitte y in mm [0]: ") or 0)
            cz = float(input(f"   Plattenmitte z in mm [{args.plate_z}]: ") or args.plate_z)
        except ValueError:
            report.section("reach", "7 · Reichweiten-Test", {"skipped": True}, ["Ungültige Eingabe, übersprungen."])
            return
    if not ask(f"Ecken um ({x:.0f} | {cy:.0f} | {cz:.0f}) anfahren? Die Platte darf noch NICHT montiert sein.", args.yes):
        report.section("reach", "7 · Reichweiten-Test", {"skipped": True}, ["Übersprungen."])
        return
    to_start_pose(robot)
    robot.set_speed(30.0)
    robot.set_zone("fine")
    corners = {"oben links (von hinten gesehen)": (cy + 185, cz + 185), "oben rechts": (cy - 185, cz + 185),
               "unten rechts": (cy - 185, cz - 185), "unten links": (cy + 185, cz - 185)}
    results, text = [], []
    for name, (y, z) in corners.items():
        entry = {"corner": name, "target": [x, y, z], "reached": False}
        try:
            robot.move_cartesian([x, y, z], PEN_QUAT, 60.0)
            xyz, _ = robot.get_cartesian()
            joints = robot.get_joints()
            margins = [round(min(j - low, high - j), 1) for j, (low, high) in zip(joints, JOINT_LIMITS)]
            entry.update(reached=max(abs(a - b) for a, b in zip(xyz, [x, y, z])) < 1.0,
                         joints=joints, margin_deg=margins)
            text.append(f"{name}: erreicht, Gelenke {joints}, kleinster Abstand zur Achsgrenze "
                        f"{min(margins)}° (Achse {margins.index(min(margins)) + 1}).")
        except ProtocolError as exc:
            entry["error"] = str(exc)
            text.append(f"{name}: NICHT erreicht ({exc}). Controller prüfen, ggf. PP to Main.")
            results.append(entry)
            break
        results.append(entry)
    try:
        robot.move_joints(START_JOINTS, 60.0)
    except ProtocolError:
        pass
    report.section("reach", "7 · Reichweiten-Test", {"plane_x": x, "center": [cy, cz], "corners": results}, text)


def step_checklist(report: Report, args: argparse.Namespace) -> None:
    print()
    print("== 8 · Checkliste (Antwort eintippen, Enter = offen)")
    answers = {}
    for item in CHECKLIST:
        answers[item] = "" if args.yes else input(f"   {item} ").strip()
    report.section("checklist", "8 · Checkliste", answers,
                   [f"- [{'x' if answer else ' '}] {item} {answer}".rstrip() for item, answer in answers.items()])


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose für den Robotertermin")
    parser.add_argument("--ip", default="192.168.0.30")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--logger-port", type=int, default=5001)
    parser.add_argument("--plate-x", type=float, default=450.0)
    parser.add_argument("--plate-z", type=float, default=350.0)
    parser.add_argument("--yes", action="store_true", help="alle Rückfragen mit Ja beantworten (nur Fake-Controller!)")
    parser.add_argument("--quick", action="store_true", help="verkürzter Bewegungstest")
    parser.add_argument("--no-motion", action="store_true", help="nur lesen, nichts bewegen")
    args = parser.parse_args()
    if args.yes and args.ip not in ("127.0.0.1", "localhost"):
        print("--yes ist nur gegen den Fake-Controller (127.0.0.1) erlaubt.")
        return 2

    report = Report(args)
    robot = AbbClient(args.ip, args.port, timeout=10.0)
    print(f"Verbinde mit {args.ip}:{args.port} …")
    try:
        robot.connect()
    except ProtocolError as exc:
        print(f"Keine Verbindung: {exc}")
        print("Prüfen: Ethernet, Laptop-IP 192.168.0.100, Automatik, Motoren an, PP to Main, Play.")
        return 1
    try:
        step_ping(robot, report)
        step_info(robot, report)
        step_pose(robot, report)
        step_logger(args, report)
        if not args.no_motion:
            step_motion(robot, report, args)
            step_buffer(robot, report, args)
            step_reach(robot, report, args)
        step_checklist(report, args)
    except KeyboardInterrupt:
        report.lines += ["", "**Abgebrochen mit Strg+C.**"]
        print("\nAbgebrochen.")
    except ProtocolError as exc:
        report.lines += ["", f"**Abbruch wegen Fehler:** {exc}"]
        report.data["error"] = str(exc)
        print(f"\nFehler: {exc}")
    finally:
        robot.close()
        stem = report.save()
        print(f"\nProtokoll gespeichert: {stem}.json und {stem}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
