"""How the Dashboard talks to the helper: requests out, answers and copies in.

The Dashboard writes one request at a time to `<state>/outbox/request` (docs/helper-under-the-
hood.md has the format), and reads what the helper writes to `/helper`, which it can't write:
the answer to the last request, copies of your settings and devices, which lines of .env are
set (names only), and a heartbeat.
"""

from __future__ import annotations

import contextlib
import os
import re
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# The most of any file of the helper's that's read.
MAX_READ = 256 * 1024
# The helper counts as running while its heartbeat is younger than this, in seconds. It
# writes one every 30 seconds, and after every request.
ALIVE_FOR = 90
# What the helper accepts from the Dashboard (src/ok3d/helper.py has the full checks).
MAX_FILE = 64 * 1024
ENV_NAMES = ("UNIFI_API_KEY", "NTFY_TOPIC", "NTFY_TOKEN", "SMTP_PASSWORD")
ENV_VALUE = re.compile(r"[!#%&()*+,\-./0-9:;<=>?@A-Z\[\]^_a-z{|}~]{0,1024}")


class Busy(Exception):
    """The helper hasn't taken the last request yet, or is still carrying one out."""


@dataclass(frozen=True)
class Answer:
    """The helper's answer to the last request."""

    fields: dict[str, str]
    output: str

    @property
    def state(self) -> str:
        return self.fields.get("state", "")

    @property
    def action(self) -> str:
        return self.fields.get("action", "")

    @property
    def passed(self) -> bool:
        return self.state == "finished" and self.fields.get("exit") == "0"


def read(path: Path) -> str | None:
    try:
        with path.open("rb") as f:
            return f.read(MAX_READ).decode("utf-8", errors="replace")
    except OSError:
        return None


def answer(helper: Path) -> Answer | None:
    text = read(helper / "result")
    if text is None:
        return None
    head, _, output = text.partition("\n\n")
    return Answer(dict(line.split("=", 1) for line in head.splitlines() if "=" in line), output)


def current(helper: Path, name: str) -> str | None:
    """The helper's copy of your settings.yaml or devices.yaml; None when you have none."""
    return read(helper / f"current-{name}")


def env_set(helper: Path) -> set[str]:
    return set((read(helper / "env-set") or "").split())


def alive(helper: Path, now: float | None = None) -> bool:
    text = (read(helper / "alive") or "").strip()
    try:
        then = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return False
    return abs((time.time() if now is None else now) - then) < ALIVE_FOR


def can_apply(helper: Path) -> bool:
    """Apply stays off until the last thing the helper did was a Check that found no problems:
    a save since then, or a failed Check, turns it off again."""
    last = answer(helper)
    return last is not None and last.action == "check" and last.passed


def send(state: Path, helper: Path, action: str, name: str | None = None, body: bytes | None = None) -> str:
    """Leaves a request for the helper and returns its id. Raises Busy when one is waiting or
    running. The request is written to a temporary file and renamed into place, so the helper
    never reads half of one."""
    outbox = state / "outbox"
    last = answer(helper)
    if (outbox / "request").exists() or (last is not None and last.state == "running"):
        raise Busy
    request_id = secrets.token_hex(16)
    head = f"id={request_id}\naction={action}\n" + (f"name={name}\n" if name else "")
    data = head.encode() + (b"\n" + body if body is not None else b"")
    tmp = outbox / f".{request_id}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, outbox / "request")
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
    return request_id
