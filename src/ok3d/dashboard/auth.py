"""The Dashboard's sign-in: its password, sessions, and the limit on wrong guesses.

The Dashboard has a password of its own, separate from Grafana's admin login, because it has
to work when the cluster is down. It makes one on first start, keeps a salted hash of it in
`<state>/password.json`, and writes the password itself to `<state>/password`, readable only
by you, for the installer to show you once. Signing in gives the browser a session cookie;
sessions live in memory, so restarting the Dashboard signs everyone out.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

# No look-alikes (0/o, 1/l/i), so it's easy to read off a screen and type: kxq7-m2pa-9fht-3bnd.
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
# scrypt's cost: about 50 ms a guess here, which makes guessing slow and signing in quick.
SCRYPT = {"n": 2**14, "r": 8, "p": 1}
# How long a session lasts, from sign-in, in seconds.
SESSION_TTL = 12 * 3600
# After this many wrong passwords in WINDOW seconds, sign-in pauses for LOCKOUT seconds. It
# counts every wrong guess, from anywhere, since there's only one password to guess.
MAX_FAILURES = 5
WINDOW = 300
LOCKOUT = 60


def generate() -> str:
    """16 characters from 31, about 79 bits."""
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(4))


def hash_password(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, dklen=32, **SCRYPT).hex()


def write_private(path: Path, text: str) -> None:
    """Writes a file readable only by you, through a temporary file renamed into place."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


@dataclass
class Auth:
    state: Path
    sessions: dict[str, float] = field(default_factory=dict)  # session id -> when it ends
    failures: list[float] = field(default_factory=list)  # times of recent wrong passwords
    locked_until: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def record_path(self) -> Path:
        return self.state / "password.json"

    def ensure(self) -> bool:
        """Makes a password if there's none (or the record is damaged). Returns whether it did."""
        if self._record() is not None:
            return False
        password = generate()
        salt = secrets.token_bytes(16)
        write_private(self.record_path, json.dumps({"salt": salt.hex(), "hash": hash_password(password, salt)}))
        write_private(self.state / "password", password + "\n")
        return True

    def _record(self) -> dict[str, str] | None:
        try:
            record = json.loads(self.record_path.read_text(encoding="utf-8"))
            if isinstance(record, dict) and isinstance(record.get("hash"), str):
                bytes.fromhex(record["salt"])
                return record
        except (OSError, ValueError, TypeError, KeyError):
            pass
        return None

    def locked(self, now: float | None = None) -> bool:
        return (time.time() if now is None else now) < self.locked_until

    def sign_in(self, password: str, now: float | None = None) -> str | None:
        """Checks the password and returns a new session id, or None. Refuses every attempt,
        right or wrong, while sign-in is paused after too many wrong ones."""
        now = time.time() if now is None else now
        record = self._record()
        with self.lock:
            if self.locked(now) or record is None:
                return None
        right = hmac.compare_digest(hash_password(password, bytes.fromhex(record["salt"])), record["hash"])
        with self.lock:
            if not right:
                self.failures = [t for t in self.failures if t > now - WINDOW] + [now]
                if len(self.failures) >= MAX_FAILURES:
                    self.locked_until = now + LOCKOUT
                    self.failures = []
                return None
            session = secrets.token_urlsafe(32)
            self.sessions = {s: end for s, end in self.sessions.items() if end > now}
            self.sessions[session] = now + SESSION_TTL
            return session

    def valid(self, session: str | None, now: float | None = None) -> bool:
        if not session:
            return False
        now = time.time() if now is None else now
        with self.lock:
            end = self.sessions.get(session)
            return end is not None and end > now

    def sign_out(self, session: str | None) -> None:
        with self.lock:
            self.sessions.pop(session or "", None)
