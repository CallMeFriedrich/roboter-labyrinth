"""Make sure the server really ends after Ctrl+C.

Uvicorn shuts down gracefully: it waits for open connections (kiosk, tablet, stats iPad) and
for the application to stop. If something keeps hanging there – a tablet that went to sleep
in the middle of a WebSocket, a robot socket that does not answer – the window would only show
"Shutting down" and the port would stay taken, so the next start.bat could not start.

This guard chains itself in front of uvicorn's signal handlers: the normal graceful shutdown
runs as before, and if the process is still alive after GRACE_S seconds it is ended hard.
SQLite commits every write at once, so nothing is lost by that.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading

log = logging.getLogger("server")

GRACE_S = 6.0
_SIGNALS = [signal.SIGINT, signal.SIGTERM] + ([signal.SIGBREAK] if hasattr(signal, "SIGBREAK") else [])
_armed = threading.Event()


def _force_exit() -> None:
    if _armed.wait(GRACE_S):        # set by disarm(): the process is about to end normally
        return
    log.warning("Der Server hing beim Beenden – er wird jetzt hart beendet.")
    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:           # noqa: BLE001 - nothing must stop the exit
            pass
    sys.stdout.flush()
    os._exit(0)


def install() -> None:
    """Call while uvicorn is running (lifespan startup): its handlers are in place then."""
    for sig in _SIGNALS:
        try:
            previous = signal.getsignal(sig)
        except (ValueError, OSError):
            continue
        if getattr(previous, "_labyrinth_guard", False):
            continue

        def handler(signum, frame, previous=previous):
            if not getattr(handler, "started", False):
                handler.started = True
                log.info("Server wird beendet …")
                threading.Thread(target=_force_exit, name="shutdown-guard", daemon=True).start()
            if callable(previous):
                previous(signum, frame)
            elif previous == signal.SIG_DFL:
                raise KeyboardInterrupt

        handler._labyrinth_guard = True       # type: ignore[attr-defined]
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):         # not in the main thread (tests): nothing to guard
            pass


def disarm() -> None:
    """The application has stopped normally."""
    _armed.set()
