"""Leaderboard export as CSV (opens directly in Excel: semicolons, UTF-8 with BOM)."""
from __future__ import annotations

import csv
import io
import re
from datetime import date

MODE_LABEL = {"slow": "Langsam", "normal": "Normal", "turbo": "Turbo"}
HEADER = ["Platz im Tempo", "Tempo", "Name", "Geburtsjahr", "Alter (ca.)", "Zeit", "Zeit in ms",
          "Status", "Labyrinth", "Datum"]


def format_time(ms: int | None) -> str:
    if ms is None:
        return ""
    minutes, rest = divmod(int(ms), 60_000)
    return f"{minutes}:{rest // 1000:02d}.{rest % 1000 // 10:02d}"


def ranked(runs: list[dict]) -> list[tuple[int | None, dict]]:
    """Every run with its place on the board of its labyrinth and speed (aborted runs: None).

    Sorted like the boards: per labyrinth and speed by time, aborted runs last.
    """
    finished: dict[tuple, list[dict]] = {}
    for run in runs:
        if run["status"] == "finished" and run["time_ms"] is not None:
            finished.setdefault((run["labyrinth_id"], run["speed_mode"]), []).append(run)
    place: dict[int, int] = {}
    for group in finished.values():
        group.sort(key=lambda r: (r["time_ms"], r["id"]))
        for i, run in enumerate(group, start=1):
            place[run["id"]] = i
    order = {"slow": 0, "normal": 1, "turbo": 2}
    return sorted(((place.get(r["id"]), r) for r in runs),
                  key=lambda pr: (pr[1]["labyrinth_id"] or 0, order.get(pr[1]["speed_mode"], 1),
                                  pr[0] is None, pr[0] or 0, pr[1]["id"]))


def runs_csv(runs: list[dict], today: date | None = None) -> str:
    year = (today or date.today()).year
    out = io.StringIO()
    out.write("﻿")                                   # BOM: Excel recognises UTF-8 (ä, ö, ü)
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(HEADER)
    for place, run in ranked(runs):
        finished = run["status"] == "finished"
        writer.writerow([
            place or "", MODE_LABEL.get(run["speed_mode"], run["speed_mode"]), run["name"],
            run["birth_year"], year - run["birth_year"] if run["birth_year"] else "",
            format_time(run["time_ms"]) if finished else "", run["time_ms"] if finished else "",
            "im Ziel" if finished else "abgebrochen", run["labyrinth"] or "",
            (run["created_at"] or "").replace("T", " "),
        ])
    return out.getvalue()


def file_name(profile_name: str, today: date | None = None) -> str:
    safe = re.sub(r"[^\w-]+", "_", profile_name, flags=re.UNICODE).strip("_") or "Profil"
    return f"Bestenliste_{safe}_{(today or date.today()).isoformat()}.csv"
