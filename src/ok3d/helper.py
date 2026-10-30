"""ok3d-helper: runs `./ok3d check` and `./ok3d apply`, and saves settings, devices, and
secrets, when the Dashboard asks.

The Dashboard runs in a container and can't run anything on the host itself. When you press
Check or Apply, or saves a change, it leaves a request file in its outbox,
`<data root>/dashboard/outbox/request`:

    id=3f9a0c51d2e8b746
    action=check

This helper, a systemd user service running as you, looks for that file every few seconds.
It renames it into its own folder, `<data root>/helper/taken/`, which the Dashboard can read
but not write, checks every value again, carries it out, and writes its answer to
`<data root>/helper/result` for the page to read.

It assumes the Dashboard's container may have been taken over, so it trusts nothing in the
outbox: not the file's contents, not its type (it may be a link, a folder, or a pipe), and not
its size. The most a request can ever do is what you could do yourself: run `./ok3d check`
or `./ok3d apply`, save a settings or devices file that `./ok3d validate` passes, set one
of four lines of .env (ENV_NAMES), or look for a newer release and move to one, which
`./ok3d upgrade` takes only when its tag is signed by a key in deploy/release-signers.
docs/helper-under-the-hood.md has the whole story.

It uses only the standard library and runs on the host's own Python (`python3 -I`), so the
host needs nothing installed.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import hashlib
import itertools
import os
import re
import signal
import stat
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# The most of a file a request may carry (settings.yaml or devices.yaml), and of a request in
# all: the file, and a few short lines before it.
MAX_FILE = 64 * 1024
MAX_REQUEST = MAX_FILE + 1024
# A request older than this is refused: the page that sent it has given up waiting.
MAX_AGE = 300
# How far in the future a request's time may be, for a clock that's a little off.
MAX_SKEW = 60
# What a request may ask for, and nothing else:
#   check, apply      run ./ok3d check or ./ok3d apply
#   save-settings     check the file that follows with ./ok3d validate, then save it as settings.yaml
#   save-devices      the same for devices.yaml
#   set-env           set one line of .env (name=, one of ENV_NAMES) to the value that follows
#   look-for-release  run ./ok3d upgrade, which says whether a newer release is out
#   upgrade           start ./ok3d upgrade <version=> --yes, in a service of its own (see start_upgrade)
#   maintenance-add   run ./ok3d maintenance add <what=> <when=> <reason=>: a maintenance window
#   maintenance-end   run ./ok3d maintenance end <window=>
#   maintenance-list  run ./ok3d maintenance, which writes the windows for the Dashboard
ACTIONS = ("check", "apply", "save-settings", "save-devices", "set-env", "look-for-release", "upgrade",
           "maintenance-add", "maintenance-end", "maintenance-list")  # fmt: skip
# The files the two save actions write, in the ok3d checkout, and what ./ok3d validate calls them.
SAVES = {"save-settings": ("settings.yaml", "settings"), "save-devices": ("devices.yaml", "devices")}
# The .env lines set-env may set. Not OK3D_ADMIN_PASSWORD, ANTHROPIC_API_KEY, or DEADMAN_URL:
# choosing the admin password would let a Dashboard someone had taken over sign in to Grafana,
# a key of their own would send the agents' conversations to their account, and the dead
# man's switch could be pointed anywhere. You set those three in .env on the server. A wrong
# value in any line here only stops something working: where each is sent is a setting only
# you may change.
ENV_NAMES = ("UNIFI_API_KEY", "NTFY_TOPIC", "NTFY_TOKEN", "SMTP_PASSWORD")
# A .env value: printable characters with no spaces, quotes, backslashes, dollar signs, or
# backticks, so .env holds it as plain text that nothing reading .env can misread. Empty
# clears it. API keys, tokens, URLs, and generated passwords all fit.
ENV_VALUE = re.compile(r"[!#%&()*+,\-./0-9:;<=>?@A-Z\[\]^_a-z{|}~]{0,1024}")
# The id is the page's own random number, so it knows which answer is to its request.
ID = re.compile(r"[0-9a-f]{16,64}")
# A release to upgrade to: vX.Y.Z, as ./ok3d upgrade takes it.
VERSION = re.compile(r"v[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}")
# The lines a request's head may have, each at most once: id and action always, name only
# with set-env, version only with upgrade, and base (optional) only with a save: the SHA-256
# of the file the page showed, so a save doesn't overwrite a change made on the server since.
FIELDS = ("id", "action", "name", "base", "version", "what", "when", "reason", "window")
# A maintenance window's lines, as src/ok3d/maintenance.py checks them (a test keeps the two
# the same): what (all, or device names joined by commas), when (a length from now, or
# START/END), an optional reason (plain text), and window (a silence's id, to end it).
DEVICE = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
LOCAL = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}"
MAINTENANCE_PATTERNS = {
    "what": re.compile(rf"all|{DEVICE}(?:,{DEVICE}){{0,49}}"),
    "when": re.compile(rf"[1-9][0-9]{{0,3}}[mhd]|{LOCAL}/{LOCAL}"),
    "reason": re.compile(r"(?:[A-Za-z0-9][A-Za-z0-9 ,.'()/:_-]{0,99})?"),
    "window": re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
}
# Which of those lines each maintenance action needs, and which it may have.
MAINTENANCE_FIELDS = {"maintenance-add": (("what", "when"), ("reason",)), "maintenance-end": (("window",), ())}
# How long each action may run before it's stopped. A first apply downloads images. An
# upgrade only has to start here: it runs in a service of its own.
TIMEOUTS = {"check": 300, "apply": 3600, "save-settings": 120, "save-devices": 120, "look-for-release": 120,
            "upgrade": 60, "maintenance-add": 120, "maintenance-end": 120, "maintenance-list": 120}  # fmt: skip
# Why a request is refused while an upgrade holds its lock, which includes one from a terminal
# waiting for you to type yes.
UPGRADE_RUNNING = "an upgrade is running, or waiting on the server for a yes: wait for it to finish"
# The service an upgrade runs in, and the commands that start it and ask about it.
UPGRADE_UNIT = "ok3d-upgrade"
SYSTEMD_RUN = "systemd-run"
SYSTEMCTL = "systemctl"
# How many lines of what the command printed go into the result.
TAIL = 200
# How many recent ids are kept, so the same request can't be carried out twice.
SEEN = 100
# How many earlier copies of each file are kept in local/backups/ in the ok3d checkout.
BACKUPS = 10
# How often the outbox is looked at, in seconds.
INTERVAL = 3.0
# How often what the Dashboard shows is published again (publish()), in seconds, besides after
# every request. The Dashboard treats the helper as running while it's fresh.
PUBLISH_EVERY = 30.0
# The .env lines whose names the Dashboard may see as set or not: all of .env.example's. Only
# the names; a value is never published.
ENV_SHOWN = ("OK3D_ADMIN_PASSWORD", "UNIFI_API_KEY", "NTFY_TOPIC", "NTFY_TOKEN", "SMTP_PASSWORD",
             "DEADMAN_URL", "ANTHROPIC_API_KEY")  # fmt: skip


class Refused(Exception):
    """A request the helper won't carry out. The message is fixed text, never the request's."""


@dataclass(frozen=True)
class Request:
    id: str
    action: str
    name: str | None = None  # the .env line, for set-env
    body: bytes = b""  # the file, or the .env value
    base: str | None = None  # for a save: the SHA-256 of the file as the page showed it
    version: str | None = None  # for an upgrade: the release, vX.Y.Z
    window: tuple[str, ...] = ()  # for a maintenance action: ./ok3d maintenance's arguments


@dataclass(frozen=True)
class Folders:
    """Where the helper reads and writes, by path. open_folders() opens them for use."""

    ok3d_dir: Path  # the ok3d checkout, with the ok3d command in it
    data_root: Path  # host.dataRoot

    @property
    def outbox(self) -> Path:
        """<data root>/dashboard/outbox: the Dashboard writes requests here."""
        return self.data_root / "dashboard" / "outbox"

    @property
    def own(self) -> Path:
        """<data root>/helper: only the helper writes here; the Dashboard may read it."""
        return self.data_root / "helper"

    @classmethod
    def for_data_root(cls, ok3d_dir: Path, data_root: Path) -> Folders:
        return cls(ok3d_dir, data_root)


@dataclass(frozen=True)
class Opened:
    """The helper's folders, opened once when it starts. Everything after goes through these
    handles, never through the paths again, so a folder the Dashboard swaps for a link later
    leads nowhere: the helper keeps using the folder it opened."""

    folders: Folders
    outbox: int  # the outbox
    own: int  # <data root>/helper
    taken: int  # <data root>/helper/taken: each request is renamed in here under a new name


def open_dir(parent: int, name: str) -> int:
    """Makes (if needed) and opens a folder in another, refusing a link or someone else's."""
    with contextlib.suppress(FileExistsError):
        os.mkdir(name, 0o700, dir_fd=parent)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    except OSError:
        raise SystemExit(f"ok3d-helper: {name} isn't a folder (a link, or something else)") from None
    info = os.fstat(fd)
    if info.st_uid != os.getuid():
        os.close(fd)
        raise SystemExit(f"ok3d-helper: {name} belongs to someone else")
    os.fchmod(fd, 0o700)
    return fd


def open_folders(folders: Folders) -> Opened:
    """Checks the ok3d command is there, then makes and opens the folders, readable only by
    you. Each folder is opened from the one above it without following links."""
    if not os.access(folders.ok3d_dir / "ok3d", os.X_OK):
        raise SystemExit(f"ok3d-helper: no ok3d command in {folders.ok3d_dir}")
    root = os.open(folders.data_root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        dashboard = open_dir(root, "dashboard")
        own = open_dir(root, "helper")
    finally:
        os.close(root)
    try:
        outbox = open_dir(dashboard, "outbox")
    finally:
        os.close(dashboard)
    return Opened(folders, outbox, own, open_dir(own, "taken"))


def parse_request(data: bytes, mtime: float, now: float) -> Request:
    """Checks a request's bytes and age, and returns it, or raises Refused.

    A request is a few lines (its head), each ending in a newline. A save or set-env adds a
    blank line and then the file or the value (its body). check and apply have no body.
    """
    if len(data) > MAX_REQUEST:
        raise Refused("the request is too big")
    if not now - MAX_AGE <= mtime <= now + MAX_SKEW:
        raise Refused("the request isn't recent")
    head_bytes, blank, body = data.partition(b"\n\n")
    try:
        head = head_bytes.decode("ascii")
    except UnicodeDecodeError:
        raise Refused("the request isn't plain text") from None
    if not blank:
        # No body: the head must end in a newline.
        if not head.endswith("\n"):
            raise Refused("the request isn't finished")
        head = head[:-1]
    fields: dict[str, str] = {}
    for line in head.split("\n"):
        key, sep, value = line.partition("=")
        if not sep or key not in FIELDS:
            raise Refused("the request has a line the helper doesn't know")
        if key in fields:
            raise Refused("the request repeats a line")
        fields[key] = value
    if "id" not in fields or "action" not in fields:
        raise Refused("the request is missing a line")
    if not ID.fullmatch(fields["id"]):
        raise Refused("the request's id isn't valid")
    action = fields["action"]
    if action not in ACTIONS:
        raise Refused("the request asks for something the helper doesn't do")
    if ("name" in fields) != (action == "set-env"):
        raise Refused("the request has a line the helper doesn't know" if "name" in fields
                      else "the request is missing a line")  # fmt: skip
    if "base" in fields and (action not in SAVES or not re.fullmatch(r"[0-9a-f]{64}|none", fields["base"])):
        raise Refused("the request's base isn't valid")
    if ("version" in fields) != (action == "upgrade"):
        raise Refused("the request has a line the helper doesn't know" if "version" in fields
                      else "the request is missing a line")  # fmt: skip
    if action == "upgrade" and not VERSION.fullmatch(fields["version"]):
        raise Refused("the request's version isn't a release")
    required, optional = MAINTENANCE_FIELDS.get(action, ((), ()))
    for key, pattern in MAINTENANCE_PATTERNS.items():
        if key in fields and key not in required + optional:
            raise Refused("the request has a line the helper doesn't know")
        if key in required and key not in fields:
            raise Refused("the request is missing a line")
        if key in fields and not pattern.fullmatch(fields[key]):
            raise Refused(f"the request's {key} isn't valid")
    window: tuple[str, ...] = ()
    if action == "maintenance-add":
        window = ("add", fields["what"], fields["when"], fields.get("reason", ""))
    elif action == "maintenance-end":
        window = ("end", fields["window"])
    has_body = action in SAVES or action == "set-env"
    if bool(blank) != has_body:
        raise Refused("the request has something after it" if blank else "the request isn't finished")
    if action in SAVES:
        check_file(body)
    if action == "set-env":
        if fields["name"] not in ENV_NAMES:
            raise Refused("the request names a .env line the helper doesn't set")
        body = body.removesuffix(b"\n")
        if not ENV_VALUE.fullmatch(body.decode("ascii", errors="replace")):
            raise Refused("the value has characters .env can't hold safely")
    return Request(fields["id"], action, fields.get("name"), body, fields.get("base"), fields.get("version"), window)


def check_file(body: bytes) -> None:
    """A settings or devices file: UTF-8 text, at most MAX_FILE, with no control characters
    but tabs and newlines. Whether it's valid ok3d settings is ./ok3d validate's to say."""
    if not body:
        raise Refused("the file is empty")
    if len(body) > MAX_FILE:
        raise Refused("the file is too big")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused("the file isn't UTF-8 text") from None
    if any((c < " " and c not in "\t\n") or c == "\x7f" for c in text):
        raise Refused("the file has control characters")


def find_id(data: bytes) -> str | None:
    """The request's id, if it has a valid one, so even a refusal can say which request it
    answers. Only an id that passes the check is ever repeated."""
    head = data[:MAX_REQUEST].partition(b"\n\n")[0]
    match = re.search(rb"^id=([0-9a-f]{16,64})$", head, re.MULTILINE)
    return match.group(1).decode() if match else None


# Makes each taken request's name new, with the time.
_names = itertools.count()


def take_request(opened: Opened) -> tuple[bytes, float] | None:
    """Moves the outbox's request into the helper's folder and reads it.

    Returns its bytes and modification time, None when there's no request, or raises Refused.
    The rename moves whatever is there (a link moves as a link, never what it points to), to a
    name that's new each time, so nothing left from before is ever in the way. A plain file is
    read and removed. Anything else is refused: a link or pipe is removed without being
    opened, and a folder is left where it landed, unread and untouched, because removing a
    tree someone else built is a way to make the helper fail.
    """
    name = f"{time.time_ns()}-{next(_names)}"
    try:
        os.rename("request", name, src_dir_fd=opened.outbox, dst_dir_fd=opened.taken)
    except FileNotFoundError:
        return None
    except OSError as e:
        if e.errno == errno.EXDEV:
            raise Refused("the outbox and the helper's folder are on different filesystems") from None
        raise Refused("the request couldn't be taken") from None
    info = os.stat(name, dir_fd=opened.taken, follow_symlinks=False)
    if stat.S_ISDIR(info.st_mode):
        raise Refused("the request isn't a plain file")
    try:
        if not stat.S_ISREG(info.st_mode):
            raise Refused("the request isn't a plain file")
        if info.st_nlink != 1:
            raise Refused("the request is a link to another file")
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=opened.taken)
        with os.fdopen(fd, "rb") as f:
            data = f.read(MAX_REQUEST + 1)
        return data, info.st_mtime
    finally:
        with contextlib.suppress(OSError):
            os.unlink(name, dir_fd=opened.taken)


def write_file(opened: Opened, name: str, text: str) -> None:
    """Writes a file in the helper's folder, readable only by you, through a temporary file
    renamed into place, so the Dashboard never reads half of one."""
    tmp = f".{name}.tmp"
    with contextlib.suppress(FileNotFoundError):
        os.unlink(tmp, dir_fd=opened.own)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(tmp, flags, 0o600, dir_fd=opened.own)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, name, src_dir_fd=opened.own, dst_dir_fd=opened.own)


def write_result(opened: Opened, fields: dict[str, str], output: str = "") -> None:
    """The answer the Dashboard reads: one field per line, a blank line, then what ok3d printed."""
    lines = [f"{key}={value}" for key, value in fields.items()]
    write_file(opened, "result", "\n".join(lines) + "\n\n" + output)


def seen_before(opened: Opened, request_id: str) -> bool:
    """Whether the id is one of the last SEEN carried out. Records it if not."""
    try:
        fd = os.open("seen", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=opened.own)
        with os.fdopen(fd, encoding="ascii") as f:
            seen = f.read().split()
    except FileNotFoundError:
        seen = []
    if request_id in seen:
        return True
    write_file(opened, "seen", "\n".join([*seen[-(SEEN - 1) :], request_id]) + "\n")
    return False


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_ok3d(opened: Opened, args: list[str], timeout: int) -> tuple[int, str]:
    """Runs ./ok3d with these arguments and returns its exit status and the last lines it printed."""
    ok3d_dir = opened.folders.ok3d_dir
    flags = os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    fd = os.open("output", flags, 0o600, dir_fd=opened.own)
    with os.fdopen(fd, "w+", encoding="utf-8", errors="replace") as out:
        # Its own process group, so a timeout stops everything it started, Helm and k3d too.
        process = subprocess.Popen(
            [str(ok3d_dir / "ok3d"), *args],
            cwd=ok3d_dir,
            env=ok3d_env(),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        # Wait in steps, writing the heartbeat at each, so the Dashboard knows the helper is
        # still here through an Apply that takes many minutes.
        deadline = time.monotonic() + timeout
        while True:
            try:
                status = process.wait(timeout=max(0.1, min(PUBLISH_EVERY, deadline - time.monotonic())))
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    out.write(f"\nok3d-helper: stopped ./ok3d {args[0]} after {timeout} seconds.\n")
                    status = 124
                    break
                with contextlib.suppress(OSError):
                    write_file(opened, "alive", now_utc() + "\n")
        # Anything it left running in its group goes too, whether it finished or was stopped.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        out.flush()
        out.seek(0)
        lines = out.read().splitlines()
    return status, "\n".join(lines[-TAIL:]) + "\n"


def replace_file(path: Path, data: bytes) -> None:
    """Writes a file in the ok3d checkout, readable only by you, through a temporary file
    renamed into place, after making sure it's on disk."""
    tmp = path.with_name(f".{path.name}.ok3d-helper.tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def back_up(opened: Opened, path: Path) -> None:
    """Keeps a copy of a file before it's replaced, in local/backups/ in the ok3d checkout,
    readable only by you, and only the last BACKUPS of each. The Dashboard can't see that
    folder, which matters for .env."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return
    with os.fdopen(fd, "rb") as f:
        data = f.read()
    backups = opened.folders.ok3d_dir / "local" / "backups"
    backups.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    replace_file(backups / f"{path.name}.{stamp}", data)
    old = sorted(backups.glob(f"{path.name}.2*"))
    for extra in old[:-BACKUPS]:
        extra.unlink(missing_ok=True)


def save(opened: Opened, request: Request) -> tuple[int, str]:
    """save-settings or save-devices: ./ok3d validate checks the file first, in the helper's
    own folder; only a file it passes replaces yours, after a copy of yours is kept."""
    name, kind = SAVES[request.action]
    if request.base is not None:
        now = read_own_file(opened.folders.ok3d_dir / name, MAX_FILE)
        if (hashlib.sha256(now).hexdigest() if now is not None else "none") != request.base:
            return 1, f"Not saved: {name} changed on the server since the page showed it. Open it again.\n"
    write_file(opened, f"staged-{name}", request.body.decode("utf-8"))
    try:
        args = ["validate", kind, str(opened.folders.own / f"staged-{name}")]
        if kind == "settings":
            args.append("--from-dashboard")  # the settings only you may change stay as they are
        status, output = run_ok3d(opened, args, TIMEOUTS[request.action])
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(f"staged-{name}", dir_fd=opened.own)
    if status != 0:
        return status, output + f"Not saved: your {name} is unchanged.\n"
    target = opened.folders.ok3d_dir / name
    back_up(opened, target)
    replace_file(target, request.body)
    return 0, output + f"Saved {name}.\n"


def set_env_value(opened: Opened, request: Request) -> tuple[int, str]:
    """set-env: sets one line of .env, keeping every other byte of it as it was. The value
    never goes into the answer or the log."""
    name = (request.name or "").encode()
    path = opened.folders.ok3d_dir / ".env"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        data = b""
    # Split on newlines only, as bytes, so nothing else in the file is touched: not a character
    # in another encoding, not a carriage return, not an unusual separator.
    lines = data.split(b"\n") if data else []
    if data.endswith(b"\n"):
        lines.pop()
    new = name + b"=" + request.body
    # Its first line takes the new value and any later ones go, since ./ok3d reads the last.
    out: list[bytes] = []
    placed = False
    for line in lines:
        if line.startswith(name + b"="):
            if not placed:
                out.append(new)
                placed = True
        else:
            out.append(line)
    if not placed:
        out.append(new)
    back_up(opened, path)
    replace_file(path, b"\n".join(out) + b"\n")
    return 0, f"Saved {request.name} in .env.\n"


def ok3d_env() -> dict[str, str]:
    """The environment ./ok3d runs with: the helper's, without OK3D_SETTINGS and the like, so
    it reads the same files the helper writes, and fetches releases from where it should."""
    return {k: v for k, v in os.environ.items() if not k.startswith("OK3D_")}


def upgrading(ok3d_dir: Path) -> bool:
    """Whether an upgrade is running: one from the Dashboard (its service is active), or one
    from a terminal (./ok3d upgrade holds a lock on local/upgrading, which the system lets go
    of when it ends, however it ends). While one is, the helper takes no other request: an
    Apply or a save partway through would race it."""
    try:
        fd = os.open(ok3d_dir / "local" / "upgrading", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        pass  # no lock file: no upgrade has run from here
    else:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        finally:
            os.close(fd)  # which lets go of the lock, if it was taken here
    try:
        return subprocess.run([SYSTEMCTL, "--user", "is-active", "--quiet", UPGRADE_UNIT], check=False, env=ok3d_env(),
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=30).returncode == 0  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return False


def start_upgrade(opened: Opened, request: Request) -> tuple[int, str]:
    """upgrade: starts ./ok3d upgrade <version> --yes as a service of its own, and answers once
    it has started. Not under the helper: partway through, the new release's ./ok3d install
    restarts the helper's service, which stops everything the helper started. ./ok3d upgrade
    checks the version again (a release, newer than this one, signed by a key it knows), and
    writes how it's going to the helper's folder, where Home shows it."""
    ok3d_dir = opened.folders.ok3d_dir
    process = subprocess.run(
        [SYSTEMD_RUN, "--user", f"--unit={UPGRADE_UNIT}", "--collect", "--quiet",
         f"--working-directory={ok3d_dir}", f"--setenv=PATH={os.environ.get('PATH', '/usr/bin:/bin')}",
         # So ./ok3d upgrade also writes a refusal for Home, which would otherwise show nothing.
         "--setenv=OK3D_UPGRADE_FROM_DASHBOARD=yes",
         "--", str(ok3d_dir / "ok3d"), "upgrade", str(request.version), "--yes"],
        check=False, env=ok3d_env(), stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace",
        timeout=TIMEOUTS["upgrade"],
    )  # fmt: skip
    if process.returncode != 0:
        return process.returncode, process.stdout + process.stderr + "The upgrade didn't start.\n"
    return 0, (f"Started the upgrade to {request.version}. Home shows how it's going; the Dashboard "
               "restarts partway, so you'll sign in again.\n")  # fmt: skip


def carry_out(opened: Opened, request: Request) -> tuple[int, str]:
    if request.action in SAVES:
        return save(opened, request)
    if request.action == "set-env":
        return set_env_value(opened, request)
    if request.action == "upgrade":
        return start_upgrade(opened, request)
    if request.action.startswith("maintenance-"):
        return run_ok3d(opened, ["maintenance", *request.window], TIMEOUTS[request.action])
    if request.action == "look-for-release":
        return run_ok3d(opened, ["upgrade"], TIMEOUTS[request.action])
    return run_ok3d(opened, [request.action], TIMEOUTS[request.action])


def handle_once(opened: Opened, now: float | None = None) -> str | None:
    """Carries out the outbox's request, if there is one. Returns what happened, for the log.

    Every request that's taken gets an answer, so the page never waits forever."""
    request_id = None
    try:
        taken = take_request(opened)
        if taken is None:
            return None
        request_id = find_id(taken[0])
        request = parse_request(*taken, now=time.time() if now is None else now)
        if seen_before(opened, request.id):
            raise Refused("the request was carried out already")
        answer = {"id": request.id, "action": request.action} | ({"name": request.name} if request.name else {})
        # Running first, then whether an upgrade is: ./ok3d upgrade takes its lock first, then
        # reads this answer, so whichever comes second sees the other, and an upgrade never
        # starts under an Apply, nor an Apply under an upgrade.
        write_result(opened, answer | {"state": "running"})
        if upgrading(opened.folders.ok3d_dir):
            raise Refused(UPGRADE_RUNNING)
    except Refused as e:
        fields = {"id": request_id} if request_id else {}
        write_result(opened, fields | {"state": "refused", "reason": str(e), "finished": now_utc()})
        return f"refused a request: {e}"
    try:
        status, output = carry_out(opened, request)
    except (OSError, subprocess.TimeoutExpired):
        reason = "the file couldn't be saved" if request.action in (*SAVES, "set-env") else "the ok3d command couldn't run"
        write_result(opened, answer | {"state": "failed", "reason": reason, "finished": now_utc()})
        return f"couldn't carry out {describe(request)}"
    write_result(opened, answer | {"state": "finished", "exit": str(status), "finished": now_utc()}, output)
    return f"ran {describe(request)}: exit {status}"


def describe(request: Request) -> str:
    """What a request was, for the log: its action and id, both checked already, never its body."""
    what = {"check": "./ok3d check", "apply": "./ok3d apply", "look-for-release": "./ok3d upgrade",
            "upgrade": f"./ok3d upgrade {request.version}",
            "maintenance-add": "./ok3d maintenance add", "maintenance-end": "./ok3d maintenance end",
            "maintenance-list": "./ok3d maintenance"}.get(request.action, request.action)  # fmt: skip
    return f"{what} for {request.id}"


def read_own_file(path: Path, limit: int) -> bytes | None:
    """A file of yours in the ok3d checkout, if it's a plain file (not a link) of at most
    limit bytes; None otherwise."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            return None
        data = f.read(limit + 1)
    return data if len(data) <= limit else None


def publish(opened: Opened) -> None:
    """What the Dashboard shows, written to the helper's folder, which it can read:
    - current-settings.yaml and current-devices.yaml: copies of yours, which aren't secret,
      so it can show them and you can change them there (missing when you have none).
    - env-set: the names of the lines in .env that have a value, one per line. Never a value.
    - upgrade: rewritten only when it says an upgrade is running and none is.
    - alive: when this was last written, so the Dashboard knows the helper is running.
    """
    ok3d_dir = opened.folders.ok3d_dir
    for name in ("settings.yaml", "devices.yaml"):
        data = read_own_file(ok3d_dir / name, MAX_FILE)
        if data is None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(f"current-{name}", dir_fd=opened.own)
        else:
            write_file(opened, f"current-{name}", data.decode("utf-8", errors="replace"))
    env = read_own_file(ok3d_dir / ".env", 4 * 1024 * 1024) or b""
    values: dict[bytes, bytes] = {}
    for line in env.split(b"\n"):
        key, sep, value = line.partition(b"=")
        if sep:
            # As ./ok3d reads it: the last line counts, with one quote taken off each end.
            if value[:1] in (b'"', b"'"):
                value = value[1:]
            if value[-1:] in (b'"', b"'"):
                value = value[:-1]
            values[key] = value
    set_names = [n for n in ENV_SHOWN if values.get(n.encode())]
    write_file(opened, "env-set", "".join(f"{n}\n" for n in set_names))
    clear_stopped_upgrade(opened)
    write_file(opened, "alive", now_utc() + "\n")


def clear_stopped_upgrade(opened: Opened) -> None:
    """An upgrade that says it's running when none is (the machine restarted partway) is
    marked as stopped, so Home doesn't show it running forever. ./ok3d upgrade writes the
    file, in the helper's folder, as you.

    It asks whether one is running first, and reads the file only if none is: ./ok3d upgrade
    writes its last state before it ends, so a file read after it ended is never one it will
    change again. Read first, a running one could finish in between, and be marked stopped."""
    if upgrading(opened.folders.ok3d_dir):
        return
    try:
        fd = os.open("upgrade", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=opened.own)
    except OSError:
        return
    with os.fdopen(fd, "rb") as f:
        text = f.read(4096).decode("utf-8", errors="replace")
    fields = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    # Asked again: an upgrade from a terminal may have taken the lock and written its first
    # state since the first ask.
    if fields.get("state") != "running" or upgrading(opened.folders.ok3d_dir):
        return
    fields |= {"state": "failed", "step": f"it stopped partway, at {fields.get('step', 'a step')} (the server "
               "restarted, say): docs/upgrading.md says how to carry on", "finished": now_utc()}  # fmt: skip
    write_file(opened, "upgrade", "".join(f"{k}={v}\n" for k, v in fields.items()))


def clear_unfinished(opened: Opened) -> None:
    """An answer still saying running when the helper starts is from a helper that stopped
    partway (a restart, a reboot): say so, so the Dashboard doesn't wait for it forever."""
    try:
        fd = os.open("result", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=opened.own)
    except FileNotFoundError:
        return
    with os.fdopen(fd, "rb") as f:
        head = f.read(MAX_REQUEST).decode("utf-8", errors="replace").partition("\n\n")[0]
    fields = dict(line.split("=", 1) for line in head.splitlines() if "=" in line)
    if fields.get("state") == "running":
        fields |= {"state": "failed", "reason": "the helper stopped while it ran", "finished": now_utc()}
        write_result(opened, fields)


def watch(folders: Folders) -> None:
    """Looks for requests until stopped. A second helper on the same data root won't start."""
    opened = open_folders(folders)
    lock = os.open("lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=opened.own)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("ok3d-helper: another helper is already running for this data root") from None
    print(f"ok3d-helper: watching {folders.outbox}", flush=True)
    clear_unfinished(opened)
    published = 0.0
    while True:
        try:
            message = handle_once(opened)
        except Exception as e:  # one bad request mustn't stop the helper
            message = f"couldn't handle a request: {type(e).__name__}"
        if message:
            print(f"ok3d-helper: {message}", flush=True)
        if message or time.monotonic() - published >= PUBLISH_EVERY:
            try:
                publish(opened)
                published = time.monotonic()
            except OSError as e:
                print(f"ok3d-helper: couldn't publish for the Dashboard: {type(e).__name__}", flush=True)
        time.sleep(INTERVAL)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ok3d-helper", description="Carries out the Dashboard's requests.")
    parser.add_argument("command", choices=("watch", "once"), help="watch the outbox, or handle one request")
    parser.add_argument("--ok3d-dir", type=Path, required=True, help="the ok3d checkout")
    parser.add_argument("--data-root", type=Path, required=True, help="host.dataRoot from settings.yaml")
    args = parser.parse_args(argv)
    folders = Folders.for_data_root(args.ok3d_dir.resolve(), args.data_root.resolve())
    if args.command == "watch":
        watch(folders)
    else:
        opened = open_folders(folders)
        print(handle_once(opened) or "ok3d-helper: no request")
        publish(opened)


if __name__ == "__main__":
    main()
