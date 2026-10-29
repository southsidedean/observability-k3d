"""The Setup page's switches and ready-made setups, and the few settings it reads.

The Dashboard has no YAML library (it uses only Python's own), so this reads and changes
settings.yaml as lines, and only in the shape settings.example.yaml has: block mappings,
each key on its own line, indented with spaces. Anything else on the way to a setting (flow
style, anchors, a key twice, tabs) raises CantEdit, and the page asks you to change that
setting on the Settings page instead. What it writes goes to the helper as a whole file, like
a save from the Settings page, so `./ok3d validate` checks it before it's saved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ok3d import __version__

# A key line: the key, then a colon, then whatever follows (a value, a comment, or nothing).
KEY_LINE = re.compile(r"(?P<indent> *)(?P<key>[A-Za-z][A-Za-z0-9_]*):(?P<rest>( .*)?)")
# What may follow a key that has more keys under it: nothing, or a comment.
NOTHING = re.compile(r"\s*(#.*)?")
# A true or false value, and an optional comment after it.
FLAG = re.compile(r" +(?P<value>true|false|True|False|TRUE|FALSE)(?P<comment>\s+#.*)?\s*")
# A plain or quoted value on one line, and an optional comment after it.
SCALAR = re.compile(
    r""" +(?:"(?P<double>[^"\\]*)"|'(?P<single>[^']*)'|(?P<plain>[^\s#'"][^#]*?))(?:\s+#.*)?\s*"""
)


class CantEdit(Exception):
    """The way to a setting isn't in a shape this can follow safely."""


def release() -> tuple[int, int]:
    """This release's version as (major, minor): 0.5.0.dev0 is (0, 5)."""
    major, minor = __version__.split(".")[:2]
    return int(major), int(minor)


def _skip(line: str) -> bool:
    """Blank lines and comments, which belong to no key."""
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _children(
    lines: list[str], start: int, end: int, parent_indent: int
) -> tuple[int | None, dict[str, int]]:
    """The keys directly under a mapping whose lines are lines[start:end]: their indent, and
    the line each is on. Raises CantEdit for anything that isn't one key per line at one indent."""
    indent: int | None = None
    keys: dict[str, int] = {}
    for i in range(start, end):
        line = lines[i]
        if _skip(line):
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise CantEdit("it's indented with tabs")
        this = len(line) - len(line.lstrip(" "))
        if indent is None:
            indent = this
        if this > indent:
            continue  # under one of the keys
        match = KEY_LINE.fullmatch(line)
        if this < indent or match is None:
            raise CantEdit("it isn't one setting per line")
        key = match["key"]
        if key in keys:
            raise CantEdit(f"{key} is in it twice")
        keys[key] = i
    return indent, keys


def _key(line: str) -> re.Match[str]:
    """A line _children found a key on, split into its parts."""
    match = KEY_LINE.fullmatch(line)
    if match is None:
        raise CantEdit("it isn't one setting per line")
    return match


def _end_of(lines: list[str], i: int, indent: int, end: int) -> int:
    """Where the block of the key on line i (at this indent) ends: the next line, before end,
    that's indented no deeper, not counting blank lines and comments."""
    j = i + 1
    while j < end:
        if not _skip(lines[j]) and len(lines[j]) - len(lines[j].lstrip(" ")) <= indent:
            break
        j += 1
    return j


@dataclass(frozen=True)
class Found:
    """Where _walk got to."""

    line: int | None  # the line of the setting, or None when it isn't there
    depth: int  # how many keys of the path were found
    indent: int  # the indent of the keys in the mapping where it stopped
    step: int  # how much deeper that mapping is than its parent
    start: int  # that mapping's lines
    end: int


def _walk(lines: list[str], path: tuple[str, ...]) -> Found:
    """Follows path through the mappings, to its setting or to where the missing part would go."""
    start, end, parent_indent = 0, len(lines), -1
    for depth, key in enumerate(path):
        indent, keys = _children(lines, start, end, parent_indent)
        if indent is None:
            indent = parent_indent + 2 if depth else 0
        step = indent - parent_indent if depth else 2
        if key not in keys:
            return Found(None, depth, indent, step, start, end)
        i = keys[key]
        if depth == len(path) - 1:
            # A value with more lines under it goes on there (YAML joins them), so the line
            # alone doesn't say what it is.
            under = range(i + 1, _end_of(lines, i, indent, end))
            if not NOTHING.fullmatch(_key(lines[i])["rest"]) and not all(_skip(lines[j]) for j in under):
                raise CantEdit(f"{key}'s value runs onto the next line")
            return Found(i, depth, indent, step, start, end)
        if not NOTHING.fullmatch(_key(lines[i])["rest"]):
            raise CantEdit(f"{key} isn't written as one setting per line")
        start, end, parent_indent = i + 1, _end_of(lines, i, indent, end), indent
    raise AssertionError("path is empty")


def read(text: str | None, path: tuple[str, ...]) -> str | None:
    """A setting's value as written, without quotes, or None when it isn't there or can't be
    read this way."""
    if text is None:
        return None
    lines = text.split("\n")
    try:
        i = _walk(lines, path).line
    except CantEdit:
        return None
    if i is None:
        return None
    match = KEY_LINE.fullmatch(lines[i])
    value = SCALAR.fullmatch(match["rest"]) if match else None
    if value is None:
        return None
    return next(v for v in (value["double"], value["single"], value["plain"]) if v is not None)


def flag(text: str | None, path: tuple[str, ...]) -> bool | None:
    """Whether a switch is on. Every switch here is off when it isn't written; None when it's
    written in a way this can't read."""
    if text is None:
        return False
    lines = text.split("\n")
    try:
        i = _walk(lines, path).line
    except CantEdit:
        return None
    if i is None:
        return False
    match = KEY_LINE.fullmatch(lines[i])
    value = FLAG.fullmatch(match["rest"]) if match else None
    return None if value is None else value["value"].lower() == "true"


def set_flag(text: str, path: tuple[str, ...], on: bool) -> str:
    """The settings with this switch set, and everything else as it was, comments too. A
    switch that isn't written yet is added at the end of the mapping it belongs in."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    value = "true" if on else "false"
    found = _walk(lines, path)
    if found.line is not None:
        i = found.line
        match = _key(lines[i])
        old = FLAG.fullmatch(match["rest"])
        if old is None and not SCALAR.fullmatch(match["rest"]):
            raise CantEdit(f"{path[-1]} isn't written as one value")
        comment = (old["comment"] or "") if old else ""
        lines[i] = f"{match['indent']}{match['key']}: {value}{comment}"
    else:
        # After the mapping's last setting, not after comments that may introduce what follows.
        at = found.end
        while at > found.start and _skip(lines[at - 1]):
            at -= 1
        new = [f"{' ' * (found.indent + found.step * n)}{key}:" for n, key in enumerate(path[found.depth:])]
        new[-1] += f" {value}"
        lines[at:at] = new
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class Switch:
    """One switch on the Setup page."""

    path: tuple[str, ...]
    name: str
    about: str
    since: tuple[int, int] = (0, 4)
    # The lines of .env it needs once it's on.
    keys: tuple[str, ...] = ()
    # Settings that must have a value before it can go on, and what to say when one hasn't.
    needs: tuple[tuple[tuple[str, ...], str], ...] = ()
    # Why it's changed only in settings.yaml on the server, when it is.
    host_only: str = ""

    @property
    def setting(self) -> str:
        return ".".join(self.path)

    @property
    def available(self) -> bool:
        return self.since <= release()

    def missing(self, text: str | None) -> list[str]:
        """What has to be set before this can go on."""
        return [say for path, say in self.needs if not read(text, path)]


MESH_AND_AGENTS = "it changes how ok3d is kept safe, so it's set in settings.yaml on the server"

MODULES = (
    Switch(("modules", "unifi"), "UniFi",
           "Your UniFi gateway, switches, and access points, and the clients on them, read from the "
           "UniFi controller through a view-only API key.",
           keys=("UNIFI_API_KEY",),
           needs=((("unifi", "url"), "your UniFi controller's address, unifi.url, in settings.yaml on the server"),)),
    Switch(("modules", "syslog"), "Syslog", "Logs from your routers, switches, and servers.", since=(0, 6)),
    Switch(("modules", "plex"), "Plex", "Your Plex server, watched as a service.", since=(0, 7)),
    Switch(("modules", "snmp"), "SNMP", "Switches and NAS that aren't UniFi.", since=(0, 7)),
    Switch(("modules", "ups"), "UPS", "A UPS, through NUT: battery, load, and power cuts.", since=(0, 7)),
    Switch(("modules", "mesh"), "The mesh", "Istio ambient, which encrypts traffic between ok3d's parts.",
           since=(0, 8), host_only=MESH_AND_AGENTS),
    Switch(("modules", "remoteAccess"), "Remote access", "Tailscale, to reach ok3d away from home.",
           since=(0, 8), host_only=MESH_AND_AGENTS),
    Switch(("modules", "agents"), "Agents", "AI agents that answer questions about your network.",
           since=(0, 9), host_only=MESH_AND_AGENTS),
)  # fmt: skip

ALERTS = (
    Switch(("alerts", "ntfy", "enabled"), "ntfy", "Alerts to your phone, through the ntfy app.",
           keys=("NTFY_TOPIC",)),
    Switch(("alerts", "email", "enabled"), "Email", "Alerts by email.", keys=("SMTP_PASSWORD",),
           needs=((("alerts", "email", "to"), "who gets them, alerts.email.to, on the Settings page"),
                  (("alerts", "email", "from"), "who sends them, alerts.email.from, on the Settings page"),
                  (("alerts", "email", "smarthost"), "the mail server, alerts.email.smarthost, in settings.yaml "
                   "on the server"))),
    Switch(("alerts", "deadman", "enabled"), "Dead man's switch",
           "An outside check, such as healthchecks.io, that tells you when ok3d stops being heard from.",
           keys=("DEADMAN_URL",)),
)  # fmt: skip

SWITCHES = {s.setting: s for s in MODULES + ALERTS}


@dataclass(frozen=True)
class Card:
    """A ready-made setup: the modules it turns on. Every other module it can change goes off."""

    id: str
    name: str
    about: str
    needs: str
    on: frozenset[str] = field(default_factory=frozenset)

    @property
    def available(self) -> bool:
        return all(SWITCHES[m].available and not SWITCHES[m].host_only for m in self.on)

    @property
    def since(self) -> tuple[int, int]:
        return max((SWITCHES[m].since for m in self.on), default=(0, 4))

    def changes(self) -> dict[str, bool]:
        """Each module switch this card sets: the ones it turns on, and the others it may change."""
        return {s.setting: s.setting in self.on for s in MODULES if s.available and not s.host_only}


CARDS = (
    Card("basic", "Basic NOC",
         "Watches your devices and your internet link: up or down, slow, or losing packets, with "
         "the metrics in Grafana and alerts sent to you.",
         "Your devices, listed on the Devices page."),
    Card("network", "Network NOC",
         "The basic NOC, and your UniFi network too: every UniFi device and port, and the clients "
         "on them.",
         "A UniFi controller and a view-only API key from it.",
         frozenset({"modules.unifi"})),
    Card("logs", "NOC with logs",
         "The network NOC, with your devices' logs kept and searchable.",
         "Devices that can send syslog.",
         frozenset({"modules.unifi", "modules.syslog"})),
    Card("agents", "NOC with agents",
         "The NOC with logs, and AI agents that answer questions about your network.",
         "An Anthropic API key.",
         frozenset({"modules.unifi", "modules.syslog", "modules.agents"})),
)  # fmt: skip

CARD_IDS = {c.id: c for c in CARDS}
