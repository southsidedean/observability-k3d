"""The Dashboard's sign-in: its password, sessions, and the limit on wrong guesses.

The Dashboard has a password of its own, separate from Grafana's admin login, because it has
to work when the cluster is down. It makes one on first start, keeps a salted hash of it in
`<state>/password.json`, and writes the password itself to `<state>/password`, readable only
by you, for the installer to show you once. Signing in gives the browser a session cookie;
sessions live in memory, so restarting the Dashboard signs everyone out. Wrong passwords are
limited for each address, with a higher limit for all of them together.
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
# Wrong passwords are counted for each address they come from: after MAX_FAILURES in WINDOW
# seconds, that address waits LOCKOUT seconds, so a device guessing on your network can't lock
# you out from another. If GLOBAL_FAILURES arrive from everywhere together in WINDOW (someone
# with many addresses), sign-in pauses for everyone for LOCKOUT seconds.
MAX_FAILURES = 5
GLOBAL_FAILURES = 50
WINDOW = 300
LOCKOUT = 60
# The most addresses remembered; the oldest are forgotten first.
MAX_CLIENTS = 1024


def generate() -> str:
    """16 characters from 31, about 79 bits."""
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(4))


def hash_password(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, dklen=32, **SCRYPT).hex()


def write_private(path: Path, text: str) -> None:
    """Writes a file readable only by you, through a temporary file renamed into place, and
    makes sure it's on disk before it counts."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Paused(Exception):
    """Sign-in is paused for this address (or everyone) after too many wrong passwords."""


@dataclass
class Auth:
    state: Path
    sessions: dict[str, float] = field(default_factory=dict)  # session id -> when it ends
    failures: dict[str, list[float]] = field(default_factory=dict)  # address -> recent wrong guesses
    locked: dict[str, float] = field(default_factory=dict)  # address -> when it may try again
    all_failures: list[float] = field(default_factory=list)
    locked_all_until: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)
    # One sign-in at a time: each check takes 16 MB and some CPU, and counting a guess before
    # the next one starts keeps the limits exact.
    checking: threading.Lock = field(default_factory=threading.Lock)

    @property
    def record_path(self) -> Path:
        return self.state / "password.json"

    def ensure(self) -> bool:
        """Makes a password if there's none (or its record is damaged). Returns whether it did.
        The password file is written first, so a crash between the two never leaves a hash
        nobody can see the password for. A record that can't be read for any other reason
        (permissions, a disk error) stops the Dashboard instead of replacing your password."""
        if self._record() is not None:
            return False
        password = generate()
        salt = secrets.token_bytes(16)
        try:
            write_private(self.state / "password", password + "\n")
            write_private(self.record_path, json.dumps({"salt": salt.hex(), "hash": hash_password(password, salt)}))
        except OSError as e:
            raise SystemExit(f"ok3d-dashboard: can't write its password in {self.state}: {e.strerror}") from None
        return True

    def _record(self) -> dict[str, str] | None:
        """The saved password's hash, or None when there's none: missing, or damaged."""
        try:
            text = self.record_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as e:
            raise SystemExit(f"ok3d-dashboard: can't read {self.record_path}: {e.strerror}") from None
        try:
            record = json.loads(text)
            if isinstance(record, dict) and isinstance(record.get("hash"), str):
                bytes.fromhex(record["salt"])
                return record
        except (ValueError, TypeError, KeyError):
            pass
        return None

    def is_locked(self, client: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self.lock:
            return now < self.locked_all_until or now < self.locked.get(client, 0.0)

    def _count_failure(self, client: str, now: float) -> None:
        recent = [t for t in self.failures.pop(client, []) if t > now - WINDOW] + [now]
        if len(recent) >= MAX_FAILURES:
            self.locked[client] = now + LOCKOUT
            recent = []
        self.failures[client] = recent
        while len(self.failures) > MAX_CLIENTS:
            self.failures.pop(next(iter(self.failures)))
        self.locked = {c: end for c, end in self.locked.items() if end > now}
        self.all_failures = [t for t in self.all_failures if t > now - WINDOW] + [now]
        if len(self.all_failures) >= GLOBAL_FAILURES:
            self.locked_all_until = now + LOCKOUT
            self.all_failures = []

    def sign_in(self, password: str, client: str = "", now: float | None = None) -> str | None:
        """Checks the password and returns a new session id, or None when it's wrong. While an
        address is paused after too many wrong guesses, every attempt from it raises Paused,
        right or wrong, without being checked."""
        with self.checking:
            now = time.time() if now is None else now
            if self.is_locked(client, now):
                raise Paused
            record = self._record()
            if record is None:
                return None
            right = hmac.compare_digest(hash_password(password, bytes.fromhex(record["salt"])), record["hash"])
            with self.lock:
                if not right:
                    self._count_failure(client, now)
                    return None
                self.failures.pop(client, None)
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
