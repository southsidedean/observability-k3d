"""How the Dashboard talks to the helper: requests out, answers and copies in.

The Dashboard writes one request at a time to `<state>/outbox/request` (docs/helper-under-the-
hood.md has the format), and reads what the helper writes to `/helper`, which it can't write:
the answer to the last request, copies of your settings and devices, which lines of .env are
set (names only), and a heartbeat. `./ok3d` writes there too: when the last Apply worked,
the newest release it found, and how an upgrade is going.
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

from ok3d import maintenance as rules  # a maintenance window's checks, the same ones ./ok3d makes

# The most of any file of the helper's that's read.
MAX_READ = 256 * 1024
# The helper counts as running while its heartbeat is younger than this, in seconds. It
# writes one every 30 seconds, and after every request.
ALIVE_FOR = 90
# What the helper accepts from the Dashboard (src/ok3d/helper.py has the full checks).
MAX_FILE = 64 * 1024
ENV_NAMES = ("UNIFI_API_KEY", "NTFY_TOPIC", "NTFY_TOKEN", "SMTP_PASSWORD")
ENV_VALUE = re.compile(r"[!#%&()*+,\-./0-9:;<=>?@A-Z\[\]^_a-z{|}~]{0,1024}")
VERSION = re.compile(r"v[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}")
# How much of the end of an upgrade's output is shown.
UPGRADE_TAIL = 16 * 1024
TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


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
    return text if TIME.fullmatch(text) else None


@dataclass(frozen=True)
class ApplyPlan:
    """What the last Check found Apply would change (./ok3d's apply_plan): state is new (no
    cluster or release yet), none, changes, or unknown (Check couldn't tell)."""

    state: str
    restart: tuple[str, ...] = ()
    stop: tuple[str, ...] = ()
    start: tuple[str, ...] = ()
    other: int = 0
    hidden: int = 0  # restart, stop, or start lines whose names couldn't be shown

    @property
    def asks(self) -> bool:
        """Whether Apply should ask first: it would restart or stop something (shown or not),
        or no one knows."""
        return bool(self.restart or self.stop or self.hidden) or self.state == "unknown"


# A part's plain name, as apply_plan.py writes it: letters, digits, spaces, and a little
# punctuation, and short. Anything else in the file is ignored.
PART = re.compile(r"[A-Za-z0-9 ,.'()/_-]{1,100}")


def apply_plan(helper: Path) -> ApplyPlan | None:
    """What the last Check said Apply would change; None before a Check that passed has said,
    or when the file isn't one ./ok3d wrote."""
    text = read(helper / "apply-plan") or ""
    state = fields_of(text).get("state", "")
    if state not in ("new", "none", "changes", "unknown"):
        return None
    parts: dict[str, list[str]] = {"restart": [], "stop": [], "start": []}
    other = hidden = 0
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key in parts:
            if PART.fullmatch(value):
                parts[key].append(value)
            else:
                hidden += 1
        elif key == "other" and re.fullmatch(r"[0-9]{1,6}", value):
            other = int(value)
    return ApplyPlan(state, tuple(parts["restart"]), tuple(parts["stop"]), tuple(parts["start"]), other, hidden)


@dataclass(frozen=True)
class Window:
    """A maintenance window, as ./ok3d maintenance wrote it (src/ok3d/maintenance.py)."""

    id: str
    what: str  # all, or device names joined by commas
    start: datetime  # UTC
    end: datetime
    start_here: str  # the server's own time, to show
    end_here: str
    reason: str

    def on(self, now: datetime) -> bool:
        return self.start <= now < self.end


# A time as the server shows it: digits, dashes, colons, spaces, and a time zone's letters.
HERE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}(?: [A-Za-z0-9+-]{1,10})?")


def maintenance(helper: Path) -> tuple[str, list[Window]] | None:
    """When ./ok3d last read the windows from Alertmanager, and the windows; None before it has.
    A line that isn't one it wrote is left out."""
    text = read(helper / "maintenance")
    checked = fields_of(text).get("checked", "")
    if text is None or not TIME.fullmatch(checked):
        return None
    found = []
    for line in text.splitlines():
        parts = line.removeprefix("window=").split(";")
        if not line.startswith("window=") or len(parts) != 7:
            continue
        window_id, what, start, end, start_here, end_here, reason = parts
        try:
            begins = datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            ends = datetime.strptime(end, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        except ValueError:
            continue
        if (rules.SILENCE_ID.fullmatch(window_id) and rules.WHAT.fullmatch(what) and HERE.fullmatch(start_here)
                and HERE.fullmatch(end_here) and rules.REASON.fullmatch(reason)):  # fmt: skip
            found.append(Window(window_id, what, begins, ends, start_here, end_here, reason))
    return checked, found


def fields_of(text: str | None) -> dict[str, str]:
    return dict(line.split("=", 1) for line in (text or "").splitlines() if "=" in line)


@dataclass(frozen=True)
class Newest:
    """What the last look for a release found: when, and the newer release (None if none was)."""

    checked: str
    release: str | None


def newest_release(helper: Path) -> Newest | None:
    """The answer ./ok3d upgrade left when it last looked for a release; None before it has, or
    when the file isn't one it wrote."""
    fields = fields_of(read(helper / "newest-release"))
    checked, newest = fields.get("checked", ""), fields.get("newest", "")
    if not TIME.fullmatch(checked) or not (newest == "none" or VERSION.fullmatch(newest)):
        return None
    return Newest(checked, None if newest == "none" else newest)


def is_newer(tag: str, version: str) -> bool:
    """Whether release tag vX.Y.Z is newer than version (such as 0.5.0 or 0.5.1.dev0). A
    development version comes before its release, as in ./ok3d's is_newer."""
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", version)
    if not VERSION.fullmatch(tag) or match is None:
        return False
    want = tuple(int(n) for n in tag[1:].split("."))
    have = tuple(int(n) for n in match.groups())
    return want > have or (want == have and "dev" in version)


@dataclass(frozen=True)
class Upgrade:
    """How the last upgrade went, as ./ok3d upgrade wrote it, and the end of its output."""

    fields: dict[str, str]
    output: str

    @property
    def state(self) -> str:
        return self.fields.get("state", "")


def upgrade(helper: Path) -> Upgrade | None:
    """The last upgrade, if there has been one."""
    fields = fields_of(read(helper / "upgrade"))
    if fields.get("state") not in ("running", "finished", "failed"):
        return None
    return Upgrade(fields, read_tail(helper / "upgrade-output", UPGRADE_TAIL))


def read_tail(path: Path, limit: int) -> str:
    """The last limit bytes of a file, from the start of a line, or "" when it can't be read."""
    try:
        with path.open("rb") as f:
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - limit))
            data = f.read(limit)
    except OSError:
        return ""
    if len(data) == limit and b"\n" in data:
        data = data.split(b"\n", 1)[1]
    return data.decode("utf-8", errors="replace")


def upgrading(helper: Path) -> bool:
    """Whether an upgrade says it's running. The helper also refuses every request while one is."""
    last = upgrade(helper)
    return last is not None and last.state == "running"


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
         base: str | None = None, version: str | None = None, extra: dict[str, str] | None = None) -> str:  # fmt: skip
    """Leaves a request for the helper and returns its id. Raises Busy when one of ours is
    waiting or running, and Unavailable when the outbox can't be written. The request is
    written to a temporary file and renamed into place, so the helper never reads half of
    one."""
    with _sending:
        if busy(state, helper):
            raise Busy
        request_id = secrets.token_hex(16)
        head = (f"id={request_id}\naction={action}\n" + (f"name={name}\n" if name else "")
                + (f"base={base}\n" if base else "") + (f"version={version}\n" if version else "")
                + "".join(f"{key}={value}\n" for key, value in (extra or {}).items()))  # fmt: skip
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
