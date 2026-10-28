"""ok3d-helper: runs `./ok3d check` and `./ok3d apply` when the Dashboard asks.

The Dashboard runs in a container and can't run anything on the host itself. When you press
Check or Apply, it leaves a request file in its outbox, `<data root>/dashboard/outbox/request`:

    id=3f9a0c51d2e8b746
    action=check

This helper, a systemd user service running as you, looks for that file every few seconds.
It renames it into its own folder, `<data root>/helper/`, which the Dashboard can read but not
write, checks every value again, runs the `ok3d` command, and writes its answer to
`<data root>/helper/result` for the page to read.

It assumes the Dashboard's container may have been taken over, so it trusts nothing in the
outbox: not the file's contents, not its type (it may be a link, a folder, or a pipe), and not
its size. The most a request can ever do is run `./ok3d check` or `./ok3d apply`, which you
could run yourself. docs/helper-under-the-hood.md has the whole story.

It uses only the standard library and runs on the host's own Python (`python3 -I`), so the
host needs nothing installed.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import os
import re
import shutil
import signal
import stat
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# The most of a request that's read. A real one is under 100 bytes.
MAX_REQUEST = 4096
# A request older than this is refused: the page that sent it has given up waiting.
MAX_AGE = 300
# How far in the future a request's time may be, for a clock that's a little off.
MAX_SKEW = 60
# What a request may ask for, and nothing else.
ACTIONS = ("check", "apply")
# The id is the page's own random number, so it knows which answer is to its request.
ID = re.compile(r"[0-9a-f]{16,64}")
# The fields a request has, each exactly once.
FIELDS = ("id", "action")
# How long each action may run before it's stopped. A first apply downloads images.
TIMEOUTS = {"check": 300, "apply": 3600}
# How many lines of what the command printed go into the result.
TAIL = 200
# How many recent ids are kept, so the same request can't be carried out twice.
SEEN = 100
# How often the outbox is looked at, in seconds.
INTERVAL = 3.0


class Refused(Exception):
    """A request the helper won't carry out. The message is fixed text, never the request's."""


@dataclass(frozen=True)
class Request:
    id: str
    action: str


@dataclass(frozen=True)
class Folders:
    """Where the helper reads and writes."""

    ok3d_dir: Path  # the ok3d checkout, with the ok3d command in it
    outbox: Path  # <data root>/dashboard/outbox: the Dashboard writes requests here
    own: Path  # <data root>/helper: only the helper writes here

    @classmethod
    def for_data_root(cls, ok3d_dir: Path, data_root: Path) -> Folders:
        return cls(ok3d_dir, data_root / "dashboard" / "outbox", data_root / "helper")


def parse_request(data: bytes, mtime: float, now: float) -> Request:
    """Checks a request's bytes and age, and returns it, or raises Refused."""
    if len(data) > MAX_REQUEST:
        raise Refused("the request is too big")
    if not now - MAX_AGE <= mtime <= now + MAX_SKEW:
        raise Refused("the request isn't recent")
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        raise Refused("the request isn't plain text") from None
    fields: dict[str, str] = {}
    # One field per line, each line ending in a newline; no blank lines or carriage returns.
    if not text.endswith("\n"):
        raise Refused("the request isn't finished")
    for line in text[:-1].split("\n"):
        key, sep, value = line.partition("=")
        if not sep or key not in FIELDS:
            raise Refused("the request has a line the helper doesn't know")
        if key in fields:
            raise Refused("the request repeats a line")
        fields[key] = value
    if set(fields) != set(FIELDS):
        raise Refused("the request is missing a line")
    if not ID.fullmatch(fields["id"]):
        raise Refused("the request's id isn't valid")
    if fields["action"] not in ACTIONS:
        raise Refused("the request asks for something the helper doesn't do")
    return Request(fields["id"], fields["action"])


def take_request(folders: Folders) -> tuple[bytes, float] | None:
    """Moves the outbox's request into the helper's own folder and reads it.

    Returns its bytes and modification time, None when there's no request, or raises Refused.
    The rename moves whatever is there (a link moves as a link, never what it points to), and
    from then on nothing in the Dashboard's reach is opened. What arrived is removed after
    reading, whatever it was.
    """
    taken = folders.own / "request"
    try:
        os.rename(folders.outbox / "request", taken)
    except FileNotFoundError:
        return None
    except OSError as e:
        if e.errno == errno.EXDEV:
            raise Refused("the outbox and the helper's folder are on different filesystems") from None
        if e.errno in (errno.EISDIR, errno.ENOTEMPTY, errno.EEXIST, errno.ENOTDIR):
            # Something left in the helper's folder is in the way: clear it and try next time.
            remove(taken)
            return None
        raise
    try:
        info = os.lstat(taken)
        if not stat.S_ISREG(info.st_mode):
            raise Refused("the request isn't a plain file")
        if info.st_nlink != 1:
            raise Refused("the request is a link to another file")
        fd = os.open(taken, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as f:
            data = f.read(MAX_REQUEST + 1)
        return data, info.st_mtime
    finally:
        remove(taken)


def remove(path: Path) -> None:
    """Removes a file, link, or folder, without following links."""
    with contextlib.suppress(FileNotFoundError):
        if stat.S_ISDIR(os.lstat(path).st_mode):
            shutil.rmtree(path)
        else:
            os.unlink(path)


def write_file(path: Path, text: str) -> None:
    """Writes a file readable only by you, through a temporary file renamed into place, so
    the Dashboard never reads half of one."""
    tmp = path.with_name(f".{path.name}.tmp")
    remove(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def write_result(folders: Folders, fields: dict[str, str], output: str = "") -> None:
    """The answer the Dashboard reads: one field per line, a blank line, then what ok3d printed."""
    lines = [f"{key}={value}" for key, value in fields.items()]
    write_file(folders.own / "result", "\n".join(lines) + "\n\n" + output)


def seen_before(folders: Folders, request_id: str) -> bool:
    """Whether the id was carried out already. Records it if not."""
    path = folders.own / "seen"
    try:
        seen = path.read_text(encoding="ascii").split()
    except FileNotFoundError:
        seen = []
    if request_id in seen:
        return True
    write_file(path, "\n".join([*seen[-(SEEN - 1) :], request_id]) + "\n")
    return False


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_ok3d(folders: Folders, action: str) -> tuple[int, str]:
    """Runs ./ok3d <action> and returns its exit status and the last lines it printed."""
    log = folders.own / "output"
    remove(log)
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as out:
        # Its own process group, so a timeout stops everything it started, Helm and k3d too.
        process = subprocess.Popen(
            [str(folders.ok3d_dir / "ok3d"), action],
            cwd=folders.ok3d_dir,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            status = process.wait(timeout=TIMEOUTS[action])
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            out.write(f"\nok3d-helper: stopped ./ok3d {action} after {TIMEOUTS[action]} seconds.\n")
            status = 124
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    return status, "\n".join(lines[-TAIL:]) + "\n"


def handle_once(folders: Folders, now: float | None = None) -> str | None:
    """Carries out the outbox's request, if there is one. Returns what happened, for the log."""
    try:
        taken = take_request(folders)
        if taken is None:
            return None
        request = parse_request(*taken, now=time.time() if now is None else now)
        if seen_before(folders, request.id):
            raise Refused("the request was carried out already")
    except Refused as e:
        write_result(folders, {"state": "refused", "reason": str(e), "finished": now_utc()})
        return f"refused a request: {e}"
    write_result(folders, {"id": request.id, "action": request.action, "state": "running"})
    status, output = run_ok3d(folders, request.action)
    write_result(
        folders,
        {
            "id": request.id,
            "action": request.action,
            "state": "finished",
            "exit": str(status),
            "finished": now_utc(),
        },
        output,
    )
    return f"ran ./ok3d {request.action} for {request.id}: exit {status}"


def prepare(folders: Folders) -> None:
    """Makes the folders, readable only by you, and checks the ok3d command is there."""
    if not os.access(folders.ok3d_dir / "ok3d", os.X_OK):
        raise SystemExit(f"ok3d-helper: no ok3d command in {folders.ok3d_dir}")
    for folder in (folders.outbox, folders.own):
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        if folder.is_symlink() or not folder.is_dir():
            raise SystemExit(f"ok3d-helper: {folder} isn't a folder")


def watch(folders: Folders) -> None:
    """Looks for requests until stopped. A second helper on the same data root won't start."""
    prepare(folders)
    lock = os.open(folders.own / "lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("ok3d-helper: another helper is already running for this data root") from None
    print(f"ok3d-helper: watching {folders.outbox}", flush=True)
    while True:
        try:
            message = handle_once(folders)
        except Exception as e:  # one bad request mustn't stop the helper
            message = f"couldn't handle a request: {type(e).__name__}"
        if message:
            print(f"ok3d-helper: {message}", flush=True)
        time.sleep(INTERVAL)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ok3d-helper", description="Runs ./ok3d check and apply when the Dashboard asks.")
    parser.add_argument("command", choices=("watch", "once"), help="watch the outbox, or handle one request")
    parser.add_argument("--ok3d-dir", type=Path, required=True, help="the ok3d checkout")
    parser.add_argument("--data-root", type=Path, required=True, help="host.dataRoot from settings.yaml")
    args = parser.parse_args(argv)
    folders = Folders.for_data_root(args.ok3d_dir.resolve(), args.data_root.resolve())
    if args.command == "watch":
        watch(folders)
    else:
        prepare(folders)
        print(handle_once(folders) or "ok3d-helper: no request")


if __name__ == "__main__":
    main()
