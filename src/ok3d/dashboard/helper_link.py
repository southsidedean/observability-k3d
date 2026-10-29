"""How the Dashboard talks to the helper: requests out, answers and copies in.

The Dashboard writes one request at a time to `<state>/outbox/request` (docs/helper-under-the-
hood.md has the format), and reads what the helper writes to `/helper`, which it can't write:
the answer to the last request, copies of your settings and devices, which lines of .env are
set (names only), and a heartbeat.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import secrets
import threading
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


# How long the Dashboard waits for an answer to the request it last sent before it stops
# counting the helper as busy with it, in seconds: longer than a request may wait (5 minutes).
ANSWER_WITHIN = 600

# One request at a time from this Dashboard, however many browser tabs send at once.
_sending = threading.Lock()


class Busy(Exception):
    """The helper hasn't answered the last request yet, or is still carrying one out."""


class Unavailable(Exception):
    """The outbox can't be written (missing, or not the Dashboard's)."""


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


def applied(helper: Path) -> str | None:
    """When the last Apply that worked finished, as the helper wrote it; None before one has."""
    text = (read(helper / "applied") or "").strip()
    return text if re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", text) else None


def env_set(helper: Path) -> set[str]:
    return set((read(helper / "env-set") or "").split())


def alive(helper: Path, now: float | None = None) -> bool:
    text = (read(helper / "alive") or "").strip()
    try:
        then = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return False
    return abs((time.time() if now is None else now) - then) < ALIVE_FOR


def last_sent(state: Path) -> tuple[str, float] | None:
    """The id of the request this Dashboard last sent, and when."""
    text = (read(state / "last-sent") or "").split()
    try:
        return text[0], float(text[1])
    except (IndexError, ValueError):
        return None


def busy(state: Path, helper: Path, now: float | None = None) -> bool:
    """Whether the helper has a request of ours still to take or answer: one waiting in the
    outbox, one it says is running (while it's alive), or the last one we sent, until its
    answer arrives (or ANSWER_WITHIN passes)."""
    now = time.time() if now is None else now
    if (state / "outbox" / "request").exists():
        return True
    last = answer(helper)
    if last is not None and last.state == "running" and alive(helper, now):
        return True
    sent = last_sent(state)
    if sent is None:
        return False
    answered = last is not None and last.fields.get("id") == sent[0] and last.state != "running"
    return not answered and now - sent[1] < ANSWER_WITHIN


def can_apply(state: Path, helper: Path) -> bool:
    """Apply stays off until the helper's answer to the last request this Dashboard sent is a
    Check that found no problems. Anything sent since (a save, a key) turns it off again."""
    last = answer(helper)
    sent = last_sent(state)
    return (last is not None and sent is not None and last.fields.get("id") == sent[0]
            and last.action == "check" and last.passed)  # fmt: skip


def write_private(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    with contextlib.suppress(FileNotFoundError):
        tmp.unlink()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def send(state: Path, helper: Path, action: str, name: str | None = None, body: bytes | None = None,
         base: str | None = None) -> str:  # fmt: skip
    """Leaves a request for the helper and returns its id. Raises Busy when one of ours is
    waiting or running, and Unavailable when the outbox can't be written. The request is
    written to a temporary file and renamed into place, so the helper never reads half of
    one."""
    with _sending:
        if busy(state, helper):
            raise Busy
        request_id = secrets.token_hex(16)
        head = (f"id={request_id}\naction={action}\n" + (f"name={name}\n" if name else "")
                + (f"base={base}\n" if base else ""))  # fmt: skip
        data = head.encode() + (b"\n" + body if body is not None else b"")
        try:
            write_private(state / "last-sent", f"{request_id} {time.time()}\n".encode())
            write_private(state / "outbox" / "request", data)
        except OSError:
            raise Unavailable from None
        return request_id


def fingerprint(text: str | None) -> str:
    """What a save sends as its base: the SHA-256 of the file as the page showed it, or none
    when there was no file. The helper refuses the save if the file has changed since."""
    return "none" if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()
