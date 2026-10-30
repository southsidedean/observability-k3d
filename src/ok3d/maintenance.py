"""Maintenance windows: times when ok3d's alerts don't notify you, as Alertmanager silences.

A window covers all of ok3d, or some of the devices in devices.yaml, from now for a length or
between two times. Alerts still fire, and Grafana still shows them; only the notifications
stop. The dead man's switch (Alertmanager's Watchdog alert) is never silenced: if it were,
the service watching it would decide ok3d had stopped.

`./ok3d maintenance` runs this with the server's own Python (`python3 -I`):

    maintenance.py add WHAT WHEN REASON DEVICES_FILE
        Checks the window and prints amtool's arguments, one per line, for
        `amtool silence add`: the matchers, then --start, --end, --author, and --comment.
    maintenance.py list SILENCES_JSON
        Reads `amtool silence query -o json`, and prints ok3d's windows that haven't ended,
        one per line, for the helper's folder (the Dashboard reads them):
        window=ID;WHAT;START;END;START_HERE;END_HERE;REASON
        START and END are UTC; START_HERE and END_HERE are the server's own time.
    maintenance.py table NOTE_FILE
        The same windows, as lines a person reads.
    maintenance.py id ID
        Exits 0 if ID looks like a silence's id, and 2 if not.

WHAT is "all" or device names joined by commas. WHEN is a length from now (30m, 2h, 1d), or
START/END in the server's local time (2026-11-03T02:00/2026-11-03T04:00). REASON is a short
line of plain text, or empty. Each is checked whole, with re.fullmatch, here and by the helper,
since the Dashboard's request may come from someone who has taken it over.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEVICE = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
# All of ok3d, or up to 50 devices.
WHAT = re.compile(rf"all|{DEVICE}(?:,{DEVICE}){{0,49}}")
LENGTH = re.compile(r"([1-9][0-9]{0,3})([mhd])")
LOCAL = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}"
RANGE = re.compile(rf"({LOCAL})/({LOCAL})")
# A reason: plain text, at most 100 characters, starting with a letter or digit.
REASON = re.compile(r"(?:[A-Za-z0-9][A-Za-z0-9 ,.'()/:_-]{0,99})?")
SILENCE_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# The longest a window may last, and how far ahead one may start.
LONGEST = timedelta(days=30)
FURTHEST = timedelta(days=366)
# Every window's comment starts with this, and its author is ok3d, so ok3d's are told apart
# from silences made some other way.
AUTHOR = "ok3d"
UNITS = {"m": 60, "h": 3600, "d": 86400}
# What a silence for all of ok3d matches: every alert but the dead man's switch.
ALL = ['alertname=~".+"', "alertname!=Watchdog"]
MAX_READ = 4 * 1024 * 1024


class Refused(Exception):
    """A window that can't be set, with what to say."""


def stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def here(moment: datetime) -> str:
    """The server's own time, as a person reads it."""
    return moment.astimezone().strftime("%Y-%m-%d %H:%M %Z").strip()


def window_times(when: str, now: datetime) -> tuple[datetime, datetime]:
    """The start and end of WHEN, from now: a length, or two times in the server's local time."""
    length = LENGTH.fullmatch(when)
    if length:
        start = now
        end = now + timedelta(seconds=int(length.group(1)) * UNITS[length.group(2)])
    else:
        between = RANGE.fullmatch(when)
        if not between:
            raise Refused("When is a length (30m, 2h, 1d) or START/END, such as 2026-11-03T02:00/2026-11-03T04:00.")
        try:
            # mktime reads a time as the server's own local time.
            start, end = (datetime.fromtimestamp(time.mktime(time.strptime(t, "%Y-%m-%dT%H:%M")), UTC)
                          for t in between.groups())  # fmt: skip
        except (ValueError, OverflowError):
            raise Refused("That isn't a date and time this server can read.") from None
        if start < now:
            start = now  # already started: from now
    if end <= start:
        raise Refused("The window ends before it starts.")
    if end - start > LONGEST:
        raise Refused("A window may last at most 30 days.")
    if start - now > FURTHEST:
        raise Refused("A window may start at most a year from now.")
    return start, end


def device_names(devices_file: Path) -> set[str]:
    """The names in devices.yaml, as `name:` lines."""
    try:
        text = devices_file.read_bytes()[:MAX_READ].decode("utf-8", errors="replace")
    except OSError:
        return set()
    return set(re.findall(rf"^\s*(?:-\s+)?name:\s*['\"]?({DEVICE})['\"]?\s*$", text, re.MULTILINE))


def add(what: str, when: str, reason: str, devices_file: Path, now: datetime) -> list[str]:
    """amtool's arguments for the window, or raises Refused."""
    if not WHAT.fullmatch(what):
        raise Refused("What is all, or device names from devices.yaml joined by commas.")
    if not REASON.fullmatch(reason):
        raise Refused("The reason may have letters, digits, spaces, and , . ' ( ) / : _ -, up to 100 of them.")
    start, end = window_times(when, now)
    if what == "all":
        matchers = list(ALL)
    else:
        wanted = what.split(",")
        missing = sorted(set(wanted) - device_names(devices_file))
        if missing:
            raise Refused(f"Not in devices.yaml: {', '.join(missing)}.")
        # Alertmanager anchors a regex matcher, so this matches those names exactly.
        matchers = [f'device=~"{"|".join(sorted(set(wanted)))}"']
    comment = f"{AUTHOR}: {reason}" if reason else AUTHOR
    return [*matchers, f"--start={stamp(start)}", f"--end={stamp(end)}", f"--author={AUTHOR}", f"--comment={comment}"]


def what_of(matchers: list[dict[str, object]]) -> str | None:
    """all or the devices a silence covers, if it's one ok3d makes; None if not."""
    shape = [(m.get("name"), m.get("isEqual", True), m.get("isRegex"), m.get("value")) for m in matchers]
    if shape == [("alertname", True, True, ".+"), ("alertname", False, False, "Watchdog")]:
        return "all"
    if len(shape) == 1 and shape[0][:3] == ("device", True, True) and isinstance(shape[0][3], str):
        names = shape[0][3].split("|")
        if all(re.fullmatch(DEVICE, n) for n in names) and len(names) <= 50:
            return ",".join(names)
    return None


def parse_time(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def windows(silences: object, now: datetime) -> list[str]:
    """The note's lines: ok3d's windows that haven't ended, soonest first."""
    found = []
    for s in silences if isinstance(silences, list) else []:
        if not isinstance(s, dict) or s.get("createdBy") != AUTHOR:
            continue
        silence_id, comment = s.get("id"), s.get("comment")
        start, end = parse_time(s.get("startsAt")), parse_time(s.get("endsAt"))
        what = what_of(s.get("matchers") or [])
        if not (isinstance(silence_id, str) and SILENCE_ID.fullmatch(silence_id) and isinstance(comment, str)):
            continue
        if what is None or start is None or end is None or end <= now:
            continue
        reason = comment.removeprefix(f"{AUTHOR}:").strip() if comment.startswith(AUTHOR) else ""
        if not REASON.fullmatch(reason):
            reason = ""
        found.append((start, f"window={silence_id};{what};{stamp(start)};{stamp(end)};{here(start)};{here(end)};{reason}"))
    return [line for _, line in sorted(found)]


def table(note: str) -> list[str]:
    lines = []
    for line in note.splitlines():
        if not line.startswith("window="):
            continue
        silence_id, what, _, _, start, end, reason = line.removeprefix("window=").split(";", 6)
        who = "all of ok3d" if what == "all" else what.replace(",", ", ")
        lines.append(f"{silence_id}  {start} to {end}  {who}" + (f"  ({reason})" if reason else ""))
    return lines or ["No maintenance windows."]


def main(argv: list[str]) -> int:
    now = datetime.now(UTC)
    try:
        if len(argv) == 5 and argv[0] == "add":
            print("\n".join(add(argv[1], argv[2], argv[3], Path(argv[4]), now)))
        elif len(argv) == 2 and argv[0] == "list":
            text = Path(argv[1]).read_bytes()[:MAX_READ].decode("utf-8", errors="replace")
            print("\n".join(windows(json.loads(text or "[]"), now)))
        elif len(argv) == 2 and argv[0] == "table":
            print("\n".join(table(Path(argv[1]).read_text(encoding="utf-8", errors="replace"))))
        elif len(argv) == 2 and argv[0] == "id":
            return 0 if SILENCE_ID.fullmatch(argv[1]) else 2
        else:
            print("usage: maintenance.py add WHAT WHEN REASON DEVICES | list JSON | table NOTE | id ID", file=sys.stderr)
            return 2
    except Refused as e:
        print(e, file=sys.stderr)
        return 2
    except (OSError, ValueError):
        print("Couldn't read Alertmanager's silences.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
