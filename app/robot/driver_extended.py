"""Extended driver (smooth jog with immediate stop) – deliberately NOT implemented.

CLAUDE.md §8.5: this needs a change of SERVER.mod (or EGM / Multitasking) and
must not be built before Thomas has approved it after the robot session on
18.11. Until then the standard driver has to be sufficient on its own.

Candidates to evaluate against the RAPID manual and the controller options:
  (a) new command in SERVER.mod: `MoveL \\Conc` to a far target that is clipped
      to the channel, then StopMove → ClearPath → StartMove on a stop command,
  (b) second RAPID task (option Multitasking) as a stop channel,
  (c) EGM (Externally Guided Motion) position streaming – the best solution
      if the option is installed.
"""
from __future__ import annotations

from .driver_base import DriverError, RobotDriver


class ExtendedDriver(RobotDriver):
    name = "extended"

    @property
    def connected(self) -> bool:
        return False

    async def connect(self) -> None:
        raise DriverError("Der erweiterte Treiber ist noch nicht freigegeben. "
                          "Bitte Simulator oder Standard wählen.")

    async def disconnect(self) -> None:
        return None
