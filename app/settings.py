"""Static configuration (config.toml) and admin-changeable settings.

`Config` is read once at start-up and holds everything that must not be
changed from the UI (ports, hard limits, PIN hash). `SettingsStore` holds the
values from CLAUDE.md §8.11; they live in the database and are validated
against the hard limits on every write.
"""
from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
PIN_SALT = "roboter-labyrinth:"


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    visitor_control_hosts: list[str] = ["127.0.0.1", "::1", "localhost"]


class RobotConfig(BaseModel):
    ip: str = "192.168.0.30"
    port: int = 5000
    logger_port: int = 5001
    connect_timeout_s: float = 2.5
    command_timeout_s: float = 5.0
    reconnect_interval_s: float = 2.0
    ping_interval_s: float = 2.0
    home_joints: list[float] = [0.0, 45.0, 0.0, 0.0, -45.0, 0.0]
    home_speed: float = 100.0
    admin_jog_speed: float = 20.0


class AdminConfig(BaseModel):
    pin_sha256: str = ""
    session_hours: float = 8.0


class PathsConfig(BaseModel):
    database: str = "data/labyrinth.db"
    backups: str = "data/backups"


class WorkspaceBase(BaseModel):
    x: tuple[float, float] = (150.0, 620.0)
    y: tuple[float, float] = (-350.0, 350.0)
    z: tuple[float, float] = (80.0, 750.0)


class SimConfig(BaseModel):
    acceleration: float = 1000.0
    latency_ms: float = 15.0
    plate_origin: list[float] = [450.0, -200.0, 550.0]
    plate_quat: list[float] = [0.5, -0.5, -0.5, 0.5]
    home_position: list[float] = [374.0, 0.0, 420.0]
    auto_home: bool = True
    time_scale: float = 1.0      # > 1 lets the simulator run faster (tests only)


class KioskConfig(BaseModel):
    window_position: str = "1920,0"


class Config(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    robot: RobotConfig = Field(default_factory=RobotConfig)
    admin: AdminConfig = Field(default_factory=AdminConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    limits: dict[str, tuple[float, float]] = Field(default_factory=dict)
    workspace_base: WorkspaceBase = Field(default_factory=WorkspaceBase)
    sim: SimConfig = Field(default_factory=SimConfig)
    kiosk: KioskConfig = Field(default_factory=KioskConfig)

    def resolve(self, relative: str) -> Path:
        path = Path(relative)
        return path if path.is_absolute() else ROOT / path


def load_config(path: Path | None = None) -> Config:
    path = path or ROOT / "config.toml"
    if not path.exists():
        return Config()
    with path.open("rb") as fh:
        return Config.model_validate(tomllib.load(fh))


def hash_pin(pin: str) -> str:
    return hashlib.sha256((PIN_SALT + pin).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Admin-changeable settings
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class NumberDef:
    default: float
    minimum: float
    maximum: float
    integer: bool = False
    unit: str = ""


@dataclass(frozen=True)
class ChoiceDef:
    default: str
    choices: tuple[str, ...]


SETTING_DEFS: dict[str, NumberDef | ChoiceDef] = {
    "visitor_speed": NumberDef(50, 10, 150, unit="mm/s"),
    "auto_speed": NumberDef(250, 50, 1000, unit="mm/s"),
    "approach_speed": NumberDef(100, 20, 300, unit="mm/s"),
    "jog_rate_hz": NumberDef(25, 10, 50, unit="Hz"),
    "jog_zone": ChoiceDef("z1", ("z0", "z1", "z5")),
    "pin_diameter": NumberDef(8, 1, 14, unit="mm"),
    "wall_tolerance": NumberDef(1.0, -1, 3, unit="mm"),
    "auto_extra_margin": NumberDef(1.5, 0, 5, unit="mm"),
    "insert_depth": NumberDef(5, 0, 20, unit="mm"),
    "retract_distance": NumberDef(30, 10, 100, unit="mm"),
    "tool_roll_deg": NumberDef(0, -180, 180, unit="°"),
    "countdown_s": NumberDef(3, 0, 5, integer=True, unit="s"),
    "result_display_s": NumberDef(8, 3, 30, integer=True, unit="s"),
    "viewer_side": ChoiceDef("opposite", ("robot", "opposite")),
    "driver": ChoiceDef("sim", ("sim", "standard", "extended")),
    "timing_method": ChoiceDef("fine", ("logger", "fine", "analytic")),
}


class SettingsStore:
    """Validated key/value settings backed by the `settings` table."""

    def __init__(self, db: Any, config: Config):
        self._db = db
        self._config = config
        self._cache: dict[str, Any] = {}
        for key, definition in SETTING_DEFS.items():
            stored = db.get_setting(key, None)
            try:
                self._cache[key] = self.validate(key, stored) if stored is not None else definition.default
            except ValueError:
                self._cache[key] = definition.default

    def limits(self, key: str) -> tuple[float, float]:
        definition = SETTING_DEFS[key]
        if not isinstance(definition, NumberDef):
            raise KeyError(key)
        low, high = definition.minimum, definition.maximum
        if key in self._config.limits:
            cfg_low, cfg_high = self._config.limits[key]
            low, high = max(low, cfg_low), min(high, cfg_high)
        return low, high

    def validate(self, key: str, value: Any) -> Any:
        if key not in SETTING_DEFS:
            raise ValueError(f"Unbekannte Einstellung: {key}")
        definition = SETTING_DEFS[key]
        if isinstance(definition, ChoiceDef):
            if value not in definition.choices:
                raise ValueError(f"{key}: erlaubt sind {', '.join(definition.choices)}")
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key}: Zahl erwartet")
        low, high = self.limits(key)
        if not (low <= value <= high):
            raise ValueError(f"{key}: Wert muss zwischen {low:g} und {high:g} liegen")
        return int(round(value)) if definition.integer else float(value)

    def get(self, key: str) -> Any:
        return self._cache[key]

    def __getitem__(self, key: str) -> Any:
        return self._cache[key]

    def set(self, key: str, value: Any) -> Any:
        value = self.validate(key, value)
        self._cache[key] = value
        self._db.set_setting(key, value)
        return value

    def patch(self, values: dict[str, Any]) -> dict[str, Any]:
        validated = {key: self.validate(key, value) for key, value in values.items()}
        for key, value in validated.items():
            self._cache[key] = value
            self._db.set_setting(key, value)
        return validated

    def all(self) -> dict[str, Any]:
        return dict(self._cache)

    def describe(self) -> dict[str, dict[str, Any]]:
        """Definitions for the admin UI (limits, choices, units)."""
        out: dict[str, dict[str, Any]] = {}
        for key, definition in SETTING_DEFS.items():
            if isinstance(definition, NumberDef):
                low, high = self.limits(key)
                out[key] = {"type": "number", "min": low, "max": high,
                            "integer": definition.integer, "unit": definition.unit}
            else:
                out[key] = {"type": "choice", "choices": list(definition.choices)}
        return out
