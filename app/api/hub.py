"""Connected WebSocket clients and the admin session store."""
from __future__ import annotations

import asyncio
import hmac
import json
import secrets
import time

from fastapi import WebSocket

from ..settings import Config, hash_pin

SESSION_COOKIE = "rl_session"


class Hub:
    def __init__(self) -> None:
        self.visitors: set[WebSocket] = set()
        self.admins: set[WebSocket] = set()

    async def _send(self, group: set[WebSocket], message: dict) -> None:
        if not group:
            return
        text = json.dumps(message, ensure_ascii=False, separators=(",", ":"))

        async def one(ws: WebSocket) -> None:
            try:
                await asyncio.wait_for(ws.send_text(text), 1.0)
            except Exception:           # slow or gone client must not block the game
                group.discard(ws)
        await asyncio.gather(*(one(ws) for ws in list(group)))

    async def send_public(self, message: dict) -> None:
        await self._send(self.visitors, message)

    async def send_admin(self, message: dict) -> None:
        await self._send(self.admins, message)


class AuthError(Exception):
    pass


class Auth:
    """PIN login with in-memory sessions (lost on restart, which is fine here)."""

    MAX_FAILS = 5
    LOCK_SECONDS = 30.0

    def __init__(self, config: Config):
        self._config = config
        self._sessions: dict[str, float] = {}
        self._fails = 0
        self._locked_until = 0.0

    @property
    def max_age(self) -> int:
        return int(self._config.admin.session_hours * 3600)

    def login(self, pin: str) -> str:
        now = time.monotonic()
        if now < self._locked_until:
            raise AuthError(f"Zu viele Fehlversuche. Bitte {int(self._locked_until - now) + 1} s warten.")
        expected = self._config.admin.pin_sha256
        if not expected:
            raise AuthError("Es ist noch keine PIN gesetzt. Bitte tools\\set_pin.py ausführen.")
        if not isinstance(pin, str) or not hmac.compare_digest(hash_pin(pin), expected):
            self._fails += 1
            if self._fails >= self.MAX_FAILS:
                self._fails = 0
                self._locked_until = now + self.LOCK_SECONDS
            raise AuthError("Die PIN stimmt nicht.")
        self._fails = 0
        token = secrets.token_urlsafe(32)
        self._sessions[token] = time.time() + self.max_age
        return token

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        expires = self._sessions.get(token)
        if expires is None:
            return False
        if expires < time.time():
            self._sessions.pop(token, None)
            return False
        return True

    def logout(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)
