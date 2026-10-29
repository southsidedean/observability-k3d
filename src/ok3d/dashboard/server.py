"""The Dashboard's web server: HTTPS only, behind its own sign-in.

It has the sign-in and five pages: Home (what's left to do, Check and Apply, and What's next),
Setup (ready-made setups and switches, switches.py), Settings, Devices, and Keys. Each page
reads what the helper publishes, and each button leaves a request for it (helper_link.py).

Every page is made here, with every value escaped, and carries headers that keep it out of
frames, stop other sites' scripts, and keep it out of caches. A form is accepted only from
the Dashboard's own pages: every POST must come with an Origin header naming the Dashboard
(and, from browsers that send it, Sec-Fetch-Site: same-origin). GET never changes anything.

A slow or silent client can't hold it up: each connection's TLS handshake happens in its own
thread, with a time limit, every connection has a time limit, and only so many run at once.
"""

from __future__ import annotations

import html
import re
import socket
import ssl
import threading
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ok3d import __version__
from ok3d.dashboard import helper_link, switches
from ok3d.dashboard.auth import SESSION_TTL, Auth, Paused

# __Host-: browsers accept it only over HTTPS, for this host and every path, so no other site
# or name can set it.
COOKIE = "__Host-ok3d_session"
# Seconds a connection may take for its handshake, and between reads and writes after.
TIMEOUT = 10
# The most connections served at once; the rest are closed straight away.
MAX_CONNECTIONS = 32
# The most of a form that's read. The sign-in form is a few dozen bytes; a settings or devices
# file may be 64 KB, which a browser may send at up to six times that (a line break goes as
# %0D%0A).
MAX_FORM = 4096
MAX_FILE_FORM = 6 * 64 * 1024 + 1024

HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; "
    "frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Cross-Origin-Opener-Policy": "same-origin",
}

STYLE = b"""
:root { color-scheme: light dark; --fg: #1d1d1f; --bg: #fafafa; --muted: #6b6b70; --card: #fff;
  --line: #d9d9de; --accent: #b86e00; --bad: #b3261e; --good: #2e7d32; }
@media (prefers-color-scheme: dark) { :root { --fg: #ececf0; --bg: #16161a; --muted: #a0a0a8;
  --card: #202026; --line: #34343c; --accent: #f0a63a; --bad: #f2867d; --good: #7cc47f; } }
body { font: 16px/1.5 system-ui, sans-serif; color: var(--fg); background: var(--bg); margin: 0; }
header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px;
  border-bottom: 1px solid var(--line); }
header h1 { font-size: 18px; margin: 0; }
main { max-width: 760px; margin: 0 auto; padding: 16px; }
section { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 16px;
  margin-bottom: 16px; }
h2 { font-size: 16px; margin: 0 0 8px; }
.muted { color: var(--muted); }
.bad { color: var(--bad); }
.good { color: var(--good); }
pre { overflow-x: auto; font-size: 13px; background: var(--bg); border: 1px solid var(--line);
  border-radius: 6px; padding: 8px; }
input[type=password] { font: inherit; padding: 8px; width: 100%; box-sizing: border-box;
  border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--fg); }
button { font: inherit; padding: 8px 14px; border-radius: 6px; border: 1px solid var(--accent);
  background: var(--accent); color: #fff; cursor: pointer; }
button.plain { background: none; color: var(--fg); border-color: var(--line); }
form.inline { display: inline; }
nav a { margin-right: 12px; color: var(--fg); }
h3 { font-size: 15px; margin: 12px 0 4px; }
textarea { font: 13px/1.4 ui-monospace, monospace; width: 100%; box-sizing: border-box; padding: 8px;
  border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--fg); }
input[type=password] { max-width: 420px; }
button[disabled] { opacity: 0.5; cursor: not-allowed; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
.card { border: 1px solid var(--line); border-radius: 8px; padding: 12px; }
.card.chosen { border-color: var(--accent); }
.card p { margin: 4px 0 8px; }
ul.todo { padding-left: 20px; }
"""


@dataclass(frozen=True)
class Config:
    state: Path  # <data root>/dashboard, the Dashboard's own folder
    helper: Path  # <data root>/helper, read-only: the helper's answers
    # The Dashboard's own addresses, such as https://my-server.lan:8444. When given, a form's
    # Origin must be one of them; without, it must match the Host the browser asked for.
    origins: tuple[str, ...] = ()


def page(title: str, body: str, signed_in: bool = False) -> bytes:
    """A whole page. `body` must already be escaped."""
    sign_out = (
        '<form class="inline" method="post" action="/sign-out"><button class="plain">Sign out</button></form>'
        if signed_in
        else ""
    )
    return (
        "<!doctype html><html lang=en><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)} · ok3d</title><link rel=stylesheet href=/style.css>"
        f"<header><h1>ok3d</h1>{NAV if signed_in else ''}{sign_out}</header><main>{body}</main></html>"
    ).encode()


NAV = (
    '<nav><a href="/">Home</a> <a href="/setup">Setup</a> <a href="/settings">Settings</a> '
    '<a href="/devices">Devices</a> <a href="/keys">Keys</a></nav>'
)

# What each page says about saving: the helper checks first, and keeps your old file.
SAVE_NOTE = (
    "<p class=muted>Saving sends this to the helper, which checks it with <code>./ok3d validate</code> "
    "and saves it only if it passes, keeping a copy of the old one. Home shows the answer.</p>"
)


def answer_section(config: Config) -> str:
    last = helper_link.answer(config.helper)
    if last is None:
        return "<section><h2>The helper's last answer</h2><p class=muted>None yet.</p></section>"
    state = last.state or "unknown"
    status = {"finished": "good" if last.passed else "bad", "refused": "bad", "failed": "bad"}
    words = {
        "running": "is running",
        "finished": f"finished with exit status {last.fields.get('exit', '?')}",
        "refused": f"was refused: {last.fields.get('reason', '')}",
        "failed": f"couldn't run: {last.fields.get('reason', '')}",
    }
    what = last.action or "a request"
    if last.fields.get("name"):
        what += f" {last.fields['name']}"
    when = f" at {last.fields['finished']}" if "finished" in last.fields else ""
    return (
        "<section><h2>The helper's last answer</h2>"
        f'<p class="{status.get(state, "muted")}">{html.escape(what)} '
        f"{html.escape(words.get(state, state))}{html.escape(when)}.</p>"
        + (f"<pre>{html.escape(last.output)}</pre>" if last.output.strip() else "")
        + "</section>"
    )


def home(config: Config, message: str = "") -> str:
    """Home: the helper, Check and Apply, and the helper's last answer."""
    note = f"<p class=bad>{html.escape(message)}</p>" if message else ""
    if not helper_link.alive(config.helper):
        helper = (
            "<p class=bad>The helper isn't running, so Check, Apply, and saving can't happen from "
            "here. On the server: <code>systemctl --user status ok3d-helper</code>.</p>"
        )
    else:
        helper = "<p class=good>The helper is running.</p>"
    apply_note = (
        ""
        if helper_link.can_apply(config.state, config.helper)
        else "<p class=muted>Apply turns on once a Check finds no problems, and off again when anything "
        "else is sent.</p>"
    )
    disabled = "" if helper_link.can_apply(config.state, config.helper) else " disabled"
    return (
        f"<section><h2>ok3d {html.escape(__version__)}</h2>{note}{helper}"
        "<p>Check that the server and your settings are ready, then Apply to make the cluster and "
        "deploy, or bring it up to date with your settings.</p>"
        '<form class="inline" method="post" action="/check"><button>Check</button></form> '
        f'<form class="inline" method="post" action="/apply"><button{disabled}>Apply</button></form>'
        f"{apply_note}</section>" + todo_section(config) + next_section(config) + answer_section(config)
    )


# Where Keys come from: the ones the Dashboard can set, and the rest, set only on the server.
def key_place(name: str) -> str:
    return "on the Keys page" if name in helper_link.ENV_NAMES else "in .env on the server"


# A device in devices.yaml: every one has a name.
DEVICE_NAME = re.compile(r"^\s*(?:-\s+)?name:\s*\S", re.MULTILINE)


def todo(config: Config) -> list[str]:
    """What's left before ok3d can do its job, each already escaped: settings, the keys each
    switched-on part needs, somewhere for alerts to go, and devices to watch."""
    settings = helper_link.current(config.helper, "settings.yaml")
    if settings is None:
        return ["There's no <code>settings.yaml</code> on the server yet. Make it there from "
                "<code>settings.example.yaml</code> (the installer does this for you)."]  # fmt: skip
    have = helper_link.env_set(config.helper)
    left = []
    for switch in switches.MODULES + switches.ALERTS:
        on = switches.flag(settings, switch.path)
        if not switch.available or on is False:
            continue
        if on is None:
            left.append(f"Setup can't tell whether {html.escape(switch.name)} is on: look at "
                        f"<code>{switch.setting}</code> on the Settings page.")  # fmt: skip
            continue
        left += [f"{html.escape(switch.name)} is on, and needs {html.escape(say)}." for say in switch.missing(settings)]
        keys = list(switch.keys)
        if switch.setting == "alerts.ntfy.enabled" and switches.flag(settings, ("alerts", "ntfy", "useToken")):
            keys.append("NTFY_TOKEN")
        left += [f"{html.escape(switch.name)} is on, and needs <code>{k}</code>: set it {key_place(k)}."
                 for k in keys if k not in have]  # fmt: skip
    if all(switches.flag(settings, ("alerts", way, "enabled")) is False for way in ("ntfy", "email")):
        left.append('Alerts go nowhere yet: turn on ntfy or email on <a href="/setup">Setup</a>.')
    if not DEVICE_NAME.search(helper_link.current(config.helper, "devices.yaml") or ""):
        left.append('There are no devices to watch yet: add them on <a href="/devices">Devices</a>.')
    return left


def todo_section(config: Config) -> str:
    left = todo(config)
    if not left:
        return "<section><h2>Before you Apply</h2><p class=good>Nothing's missing.</p></section>"
    items = "".join(f"<li>{item}</li>" for item in left)
    return f"<section><h2>Before you Apply</h2><ul class=todo>{items}</ul></section>"


# What a domain or a port may look like before it goes into a link.
DOMAIN = re.compile(r"[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?")
PORT = re.compile(r"[1-9][0-9]{0,4}")


def pages_address(settings: str | None, name: str) -> str:
    """The address of one of ok3d's pages, such as https://grafana.noc.home.arpa:8443/."""
    domain = (switches.read(settings, ("tls", "domain")) or "noc.home.arpa").lower()
    port = switches.read(settings, ("cluster", "ports", "https")) or "8443"
    if not DOMAIN.fullmatch(domain) or not PORT.fullmatch(port):
        domain, port = "noc.home.arpa", "8443"
    return f"https://{name}.{domain}" + ("" if port == "443" else f":{port}") + "/"


def next_section(config: Config) -> str:
    """What's next, once an Apply has worked: the steps that make ok3d useful from your own
    devices, which the Dashboard can't do for you."""
    when = helper_link.applied(config.helper)
    if when is None:
        return ""
    settings = helper_link.current(config.helper, "settings.yaml")
    ca = html.escape(pages_address(settings, "ca"))
    grafana = html.escape(pages_address(settings, "grafana"))
    domain = html.escape(pages_address(settings, "x")[len("https://x."):].split(":")[0].rstrip("/"))
    return (
        f"<section><h2>What's next</h2><p class=good>The last Apply that worked finished at {html.escape(when)}.</p><ol>"
        f"<li>Point <code>*.{domain}</code> at this server, in your router or local DNS server "
        "(docs/certificate.md has the steps).</li>"
        f"<li>Trust ok3d's certificate authority on each device you'll use: download it from <a href=\"{ca}\">{ca}</a>.</li>"
        f'<li>Open Grafana at <a href="{grafana}">{grafana}</a>. Its user is <code>admin</code>, and its password '
        "is in <code>admin-password</code> in the data root.</li>"
        "<li>Send yourself a test alert: <code>./ok3d test-alert</code> on the server.</li>"
        '<li>Add the rest of your devices on <a href="/devices">Devices</a>, then Check and Apply again.</li>'
        "</ol></section>"
    )


def switch_form(switch: switches.Switch, settings: str, base: str, have: set[str]) -> str:
    """One switch: what it is, its setting, what it needs, and a button, or why there isn't one."""
    on = switches.flag(settings, switch.path)
    state = {True: "<span class=good>on</span>", False: "<span class=muted>off</span>",
             None: "<span class=bad>can't tell</span>"}[on]  # fmt: skip
    why = ""
    if not switch.available:
        why = f"Comes in {switch.since[0]}.{switch.since[1]}."
        state = ""
    elif switch.host_only:
        why = f"Changed only on the server: {switch.host_only}."
    elif on is None:
        why = "settings.yaml has this in a shape the Setup page can't change: change it on the Settings page."
    elif not on and switch.missing(settings):
        why = "Before it can go on, it needs " + "; and ".join(switch.missing(settings)) + "."
    keys = ""
    if switch.keys and switch.available:
        keys = "<p class=muted>Needs " + ", ".join(
            f"<code>{k}</code> ({'set' if k in have else 'not set'}, {key_place(k)})" for k in switch.keys) + ".</p>"  # fmt: skip
    written = {True: "true", False: "false", None: switches.read(settings, switch.path)}[on]
    button = (f"<p class=muted>{html.escape(why)}</p>" if why else
              f'<input type="hidden" name="base" value="{base}"><input type="hidden" name="switch" value="{switch.setting}">'
              f'<input type="hidden" name="on" value="{"false" if on else "true"}">'
              f"<p><button>{'Turn off' if on else 'Turn on'}</button></p>")  # fmt: skip
    return (
        f'<form method="post" action="/setup"><h3>{html.escape(switch.name)} {state}</h3>'
        f"<p class=muted>{html.escape(switch.about)}"
        + (f" In settings.yaml: <code>{switch.setting}: {html.escape(written)}</code>."
           if switch.available and written is not None else "")
        + "</p>"
        f"{keys}{button}</form>"
    )


def card_html(card: switches.Card, settings: str, base: str) -> str:
    chosen = card.available and all(switches.flag(settings, SWITCH_PATHS[k]) == v for k, v in card.changes().items())
    missing = [say for k in sorted(card.on) for say in switches.SWITCHES[k].missing(settings)]
    if not card.available:
        action = f"<p class=muted>Comes in {card.since[0]}.{card.since[1]}.</p>"
    elif chosen:
        action = "<p class=good>Your setup now.</p>"
    elif missing:
        action = f"<p class=muted>Before you can choose it, it needs {html.escape('; and '.join(missing))}.</p>"
    else:
        action = (f'<form method="post" action="/setup"><input type="hidden" name="base" value="{base}">'
                  f'<input type="hidden" name="card" value="{card.id}"><button>Choose</button></form>')  # fmt: skip
    return (
        f'<div class="card{" chosen" if chosen else ""}"><h3>{html.escape(card.name)}</h3>'
        f"<p>{html.escape(card.about)}</p><p class=muted>Needs: {html.escape(card.needs)}</p>{action}</div>"
    )


SWITCH_PATHS = {s.setting: s.path for s in switches.MODULES + switches.ALERTS}


def setup_page(config: Config, message: str = "") -> str:
    """Setup: a ready-made setup, or each part switched on or off, and where alerts go. Each
    choice is saved to settings.yaml through the helper, which checks it first."""
    settings = helper_link.current(config.helper, "settings.yaml")
    note = f"<p class=bad>{html.escape(message)}</p>" if message else ""
    if settings is None:
        return (f"<section><h2>Setup</h2>{note}<p class=bad>There's no settings.yaml on the server yet. "
                "Make it there first, from settings.example.yaml.</p></section>")  # fmt: skip
    base = helper_link.fingerprint(settings)
    have = helper_link.env_set(config.helper)
    cards = "".join(card_html(c, settings, base) for c in switches.CARDS)
    modules = "".join(switch_form(s, settings, base, have) for s in switches.MODULES)
    alerts = "".join(switch_form(s, settings, base, have) for s in switches.ALERTS)
    return (
        f"<section><h2>Ready-made setups</h2>{note}<p>Choose one, or switch the parts on and off "
        "yourself below. Metrics, alerts, and ok3d's pages are always on.</p>"
        f'<div class="cards">{cards}</div>{SAVE_NOTE}</section>'
        f"<section><h2>Parts</h2>{modules}</section>"
        f"<section><h2>Where alerts go</h2>{alerts}</section>"
    )


def file_page(config: Config, name: str, message: str = "") -> str:
    """Settings or Devices: the file as it is on the server, to change and save."""
    title = {"settings.yaml": "Settings", "devices.yaml": "Devices"}[name]
    text = helper_link.current(config.helper, name)
    about = {
        "settings.yaml": (
            "<p>Your <code>settings.yaml</code>. <code>settings.example.yaml</code> explains every "
            "setting. Some settings decide where ok3d keeps its data and where it sends your keys "
            "and passwords: those you change in the file on the server, and a save here that "
            "changes them is refused (docs/helper-under-the-hood.md lists them).</p>"
        ),
        "devices.yaml": (
            "<p>Your <code>devices.yaml</code>: every device ok3d watches. "
            "<code>devices.example.yaml</code> and docs/devices.md explain each field.</p>"
        ),
    }[name]
    base = helper_link.fingerprint(text)
    if text is None:
        if name == "settings.yaml":
            return (f"<section><h2>{title}</h2>{about}<p class=bad>There's no settings.yaml on the "
                    "server yet. Make it there first, from settings.example.yaml; after that you can "
                    "change it here.</p></section>")  # fmt: skip
        text = "devices: []\n"
    note = f"<p class=bad>{html.escape(message)}</p>" if message else ""
    return (
        f"<section><h2>{title}</h2>{about}{note}"
        f'<form method="post" action="/{title.lower()}"><input type="hidden" name="base" value="{base}">'
        # The newline after <textarea> is one HTML drops, so a file that starts with a blank line keeps it.
        f'<p><textarea name="file" rows="24" spellcheck="false" aria-label="{name}">\n{html.escape(text)}</textarea></p>'
        f"{SAVE_NOTE}<p><button>Save</button></p></form></section>"
    )


# What each line of .env on the Keys page is, as (name, what it is) pairs.
KEY_ABOUT = (
    ("UNIFI_API_KEY", "The UniFi controller's API key, from a view-only admin."),
    ("NTFY_TOPIC", "Your ntfy topic: a long, random name, since anyone who knows it can read your alerts."),
    ("NTFY_TOKEN", "The ntfy topic's access token, if it needs one."),
    ("SMTP_PASSWORD", "The password of the mailbox alerts are sent from."),
)


def keys_page(config: Config, message: str = "") -> str:
    """Keys: set the lines of .env the Dashboard may set. It never shows a value back."""
    have = helper_link.env_set(config.helper)
    note = f"<p class=bad>{html.escape(message)}</p>" if message else ""
    rows = []
    for name, about in KEY_ABOUT:
        state = "<span class=good>set</span>" if name in have else "<span class=muted>not set</span>"
        rows.append(
            f'<form method="post" action="/keys"><h3><code>{name}</code> {state}</h3>'
            f"<p class=muted>{html.escape(about)}</p>"
            f'<input type="hidden" name="name" value="{name}">'
            f'<p><input type="password" name="value" autocomplete="off" aria-label="{name}"> '
            "<button>Save</button></p></form>"
        )
    others = ", ".join(
        f"<code>{n}</code> ({'set' if n in have else 'not set'})"
        for n in ("OK3D_ADMIN_PASSWORD", "DEADMAN_URL", "ANTHROPIC_API_KEY")
    )
    return (
        f"<section><h2>Keys and passwords</h2>{note}"
        "<p>Each goes into <code>.env</code> on the server. The Dashboard never shows one back: "
        "only whether it's set. Saving an empty value clears it. A value is one line of letters, "
        "digits, and symbols, with no spaces, quotes, backslashes, <code>$</code>, or backticks; "
        "one with those goes into <code>.env</code> by hand.</p>"
        + "".join(rows)
        + f"<p class=muted>Set only on the server, in <code>.env</code>: {others}.</p></section>"
    )


def sign_in_page(message: str = "") -> str:
    note = f"<p class=bad>{html.escape(message)}</p>" if message else ""
    return (
        "<section><h2>Sign in</h2>"
        "<p class=muted>The Dashboard's password was shown when ok3d was installed. It's also in "
        "<code>dashboard/password</code> in the data root, readable only by you.</p>"
        f'{note}<form method="post" action="/sign-in">'
        '<p><input type="password" name="password" autocomplete="current-password" required '
        'aria-label="Password" autofocus></p><p><button>Sign in</button></p></form></section>'
    )


def printable(text: str) -> str:
    """Text safe for the log: control characters (which could rewrite a terminal) escaped."""
    return "".join(c if c.isprintable() else f"\\x{ord(c):02x}" for c in text)


class Handler(BaseHTTPRequestHandler):
    # Each read and write after the handshake may wait this long, so a slow client gives up
    # its thread instead of keeping it.
    timeout = TIMEOUT

    # Set on the class by make_server().
    config: Config
    auth: Auth

    def setup(self) -> None:
        # The TLS handshake, here in the connection's own thread rather than where connections
        # are accepted, so a client that never finishes it holds up nobody else.
        self.request.settimeout(TIMEOUT)
        self.request.do_handshake()
        super().setup()

    # Names the server without its Python version, which would only help someone looking for holes.
    def version_string(self) -> str:
        return "ok3d-dashboard"

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        # One line a request, without the query string, which could hold anything.
        path = getattr(self, "path", "").split("?")[0]
        print(printable(f"{self.client_address[0]} {self.command} {path} {code}"), flush=True)

    def log_message(self, format: str, *args: object) -> None:  # the base class names it format
        print(printable(f"{self.client_address[0]} {format % args}"), flush=True)

    def send(self, status: int, body: bytes, content_type: str = "text/html; charset=utf-8",
             extra: dict[str, str] | None = None) -> None:  # fmt: skip
        self.send_response(status)
        for name, value in (HEADERS | (extra or {})).items():
            self.send_header(name, value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def redirect(self, to: str, extra: dict[str, str] | None = None) -> None:
        self.send(303, b"", extra={"Location": to} | (extra or {}))

    def session(self) -> str | None:
        """The session cookie's value. Read by hand: Python's cookie parser drops every cookie
        after one it can't read, so another app's odd cookie on the same host would sign you out."""
        for header in self.headers.get_all("Cookie") or []:
            for part in header.split(";"):
                name, sep, value = part.strip().partition("=")
                if sep and name == COOKIE:
                    return value
        return None

    def signed_in(self) -> bool:
        return self.auth.valid(self.session())

    def same_origin(self) -> bool:
        """Whether a POST came from one of the Dashboard's own pages."""
        origin = (self.headers.get("Origin") or "").lower()
        host = (self.headers.get("Host") or "").lower()
        fetch_site = self.headers.get("Sec-Fetch-Site")
        if fetch_site not in (None, "same-origin") or not origin:
            return False
        if self.config.origins:
            return origin in (o.lower() for o in self.config.origins)
        return bool(host) and origin == f"https://{host}"

    def read_form(self, limit: int = 0) -> dict[str, str] | None:
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return None
        if not 0 <= length <= (limit or MAX_FORM):
            return None
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/x-www-form-urlencoded":
            return None
        body = self.rfile.read(length)
        if len(body) != length:
            return None
        try:
            fields = urllib.parse.parse_qs(body.decode("ascii"), max_num_fields=10, errors="strict")
        except (ValueError, UnicodeDecodeError):
            return None
        return {k: v[0] for k, v in fields.items()}

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path == "/style.css":
            self.send(200, STYLE, "text/css; charset=utf-8")
        elif path == "/sign-in":
            if self.signed_in():
                self.redirect("/")
            else:
                self.send(200, page("Sign in", sign_in_page()))
        elif path in PAGES:
            if not self.signed_in():
                self.redirect("/sign-in")
                return
            self.send(200, page(PAGES[path][0], PAGES[path][1](self.config, ""), signed_in=True))
        else:
            self.send(404, page("Not found", "<section><h2>Not found</h2></section>", self.signed_in()))

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if not self.same_origin():
            self.send(403, page("Refused", "<section><h2>Refused</h2><p>That form didn't come from "
                                "this Dashboard.</p></section>"))  # fmt: skip
            return
        if path == "/sign-in":
            self.sign_in()
        elif path == "/sign-out":
            self.auth.sign_out(self.session())
            self.redirect("/sign-in", {"Set-Cookie": f"{COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0"})
        elif path in ACTIONS:
            if not self.signed_in():
                self.redirect("/sign-in")
                return
            ACTIONS[path](self)
        else:
            self.send(404, page("Not found", "<section><h2>Not found</h2></section>", self.signed_in()))

    def sign_in(self) -> None:
        form = self.read_form()
        if form is None:
            self.send(400, page("Sign in", sign_in_page("That didn't arrive in one piece. Try again.")))
            return
        try:
            session = self.auth.sign_in(form.get("password", ""), self.client_address[0])
        except Paused:
            self.send(429, page("Sign in", sign_in_page("Too many wrong passwords. Wait a minute, then try again.")))
            return
        if session is None:
            time.sleep(0.5)  # a little slower, for anyone guessing
            self.send(401, page("Sign in", sign_in_page("That's not the password.")))
            return
        cookie = f"{COOKIE}={session}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}"
        self.redirect("/", {"Set-Cookie": cookie})

    def ask_helper(self, back: str, render: Callable[[Config, str], str], title: str, action: str,
                   name: str | None = None, body: bytes | None = None, base: str | None = None) -> None:  # fmt: skip
        """Leaves a request for the helper, then sends you Home to watch for the answer, or
        back to the page with what went wrong."""
        if not helper_link.alive(self.config.helper):
            self.send(503, page(title, render(self.config, "The helper isn't running, so nothing was sent."), True))
            return
        try:
            helper_link.send(self.config.state, self.config.helper, action, name, body, base)
        except helper_link.Unavailable:
            self.send(503, page(title, render(self.config, "The Dashboard can't write its outbox, so nothing "
                                              "was sent. Check the Dashboard's folder on the server."), True))  # fmt: skip
            return
        except helper_link.Busy:
            self.send(409, page(title, render(self.config, "The helper is busy with the last request. "
                                              "Try again when Home shows its answer."), True))  # fmt: skip
            return
        self.redirect(back)

    def post_check(self) -> None:
        self.ask_helper("/", home, "Home", "check")

    def post_apply(self) -> None:
        if not helper_link.can_apply(self.config.state, self.config.helper):
            self.send(409, page("Home", home(self.config, "") + "<p class=bad>Run a Check that finds "
                                "no problems first.</p>", True))  # fmt: skip
            return
        self.ask_helper("/", home, "Home", "apply")

    def post_file(self, name: str, action: str, title: str) -> None:
        def render(config: Config, message: str) -> str:
            return file_page(config, name, message)

        try:
            if int(self.headers.get("Content-Length", "0")) > MAX_FILE_FORM:
                self.send(413, page(title, render(self.config, "That's bigger than 64 KB."), True))
                return
        except ValueError:
            pass
        form = self.read_form(MAX_FILE_FORM)
        text = (form or {}).get("file")
        base = (form or {}).get("base", "")
        if text is None or not re.fullmatch(r"[0-9a-f]{64}|none", base):
            self.send(400, page(title, render(self.config, "That didn't arrive in one piece. Try again."), True))
            return
        # A browser sends a text box's lines with \r\n; the files use \n.
        data = text.replace("\r\n", "\n").encode("utf-8")
        if not data.endswith(b"\n"):
            data += b"\n"
        if len(data) > helper_link.MAX_FILE:
            self.send(413, page(title, render(self.config, "That's bigger than 64 KB."), True))
            return
        self.ask_helper("/", render, title, action, body=data, base=base)

    def post_settings(self) -> None:
        self.post_file("settings.yaml", "save-settings", "Settings")

    def post_devices(self) -> None:
        self.post_file("devices.yaml", "save-devices", "Devices")

    def post_setup(self) -> None:
        form = self.read_form()
        settings = helper_link.current(self.config.helper, "settings.yaml")
        if form is None or settings is None:
            self.send(400, page("Setup", setup_page(self.config, "That didn't arrive in one piece. Try again."), True))
            return
        if form.get("base") != helper_link.fingerprint(settings):
            self.send(409, page("Setup", setup_page(self.config, "Your settings changed since that page was "
                                                    "shown. Here they are as they are now."), True))  # fmt: skip
            return
        card = switches.CARD_IDS.get(form.get("card", ""))
        switch = switches.SWITCHES.get(form.get("switch", ""))
        if card is not None and card.available:
            changes = card.changes()
            missing = [say for k in sorted(card.on) for say in switches.SWITCHES[k].missing(settings)]
        elif (switch is not None and switch.available and not switch.host_only
              and form.get("on") in ("true", "false")):  # fmt: skip
            changes = {switch.setting: form["on"] == "true"}
            missing = switch.missing(settings) if changes[switch.setting] else []
        else:
            self.send(400, page("Setup", setup_page(self.config, "The Setup page can't change that."), True))
            return
        if missing:
            self.send(400, page("Setup", setup_page(self.config, "First it needs " + "; and ".join(missing) + "."), True))
            return
        new = settings
        try:
            for setting, on in changes.items():
                if switches.flag(new, SWITCH_PATHS[setting]) != on:
                    new = switches.set_flag(new, SWITCH_PATHS[setting], on)
        except switches.CantEdit as e:
            self.send(400, page("Setup", setup_page(self.config, f"settings.yaml has {setting} in a shape the Setup "
                                                    f"page can't change safely: {e}. Change it on the Settings "
                                                    "page."), True))  # fmt: skip
            return
        if new == settings:
            self.send(200, page("Setup", setup_page(self.config, "Your settings say that already."), True))
            return
        if len(new.encode("utf-8")) > helper_link.MAX_FILE:
            self.send(413, page("Setup", setup_page(self.config, "That would make settings.yaml bigger than 64 KB."), True))
            return
        self.ask_helper("/", setup_page, "Setup", "save-settings", body=new.encode("utf-8"), base=form["base"])

    def post_keys(self) -> None:
        form = self.read_form()
        name = (form or {}).get("name", "")
        value = (form or {}).get("value", "")
        if form is None or name not in helper_link.ENV_NAMES:
            self.send(400, page("Keys", keys_page(self.config, "That didn't arrive in one piece. Try again."), True))
            return
        if not helper_link.ENV_VALUE.fullmatch(value):
            self.send(400, page("Keys", keys_page(self.config, f"{name} has characters .env can't hold "
                                                  "safely (see above). Nothing was saved."), True))  # fmt: skip
            return
        self.ask_helper("/", keys_page, "Keys", "set-env", name=name, body=value.encode("ascii"))


# The pages, by path: their title and what makes them.
PAGES: dict[str, tuple[str, Callable[[Config, str], str]]] = {
    "/": ("Home", home),
    "/setup": ("Setup", setup_page),
    "/settings": ("Settings", lambda c, m: file_page(c, "settings.yaml", m)),
    "/devices": ("Devices", lambda c, m: file_page(c, "devices.yaml", m)),
    "/keys": ("Keys", keys_page),
}

# What each form does, by path. Every one needs a session and the Dashboard's own Origin.
ACTIONS: dict[str, Callable[[Handler], None]] = {
    "/check": Handler.post_check,
    "/apply": Handler.post_apply,
    "/setup": Handler.post_setup,
    "/settings": Handler.post_settings,
    "/devices": Handler.post_devices,
    "/keys": Handler.post_keys,
}


class Server(ThreadingHTTPServer):
    """A thread for each connection, up to MAX_CONNECTIONS at once."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[Handler]) -> None:
        super().__init__(address, handler)
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def process_request(self, request: socket.socket | tuple[bytes, socket.socket], client_address: object) -> None:
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request: socket.socket | tuple[bytes, socket.socket], client_address: object) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request: object, client_address: object) -> None:
        # A handshake that failed or timed out, or a client that went away: one line, not a traceback.
        address = client_address[0] if isinstance(client_address, tuple) else client_address
        print(printable(f"{address} connection dropped"), flush=True)


def make_server(config: Config, host: str, port: int, cert: Path, key: Path) -> Server:
    """The server, with TLS 1.2 or newer and the Dashboard's certificate. It serves nothing
    without TLS."""
    auth = Auth(config.state)
    if auth.ensure():
        print(f"ok3d-dashboard: made a password; it's in {config.state / 'password'}", flush=True)
    handler = type("DashboardHandler", (Handler,), {"config": config, "auth": auth})
    server = Server((host, port), handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    # The handshake waits for each connection's own thread (Handler.setup).
    server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    return server
