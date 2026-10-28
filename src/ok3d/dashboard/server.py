"""The Dashboard's web server: HTTPS only, behind its own sign-in.

This first version has the sign-in and one page, which shows ok3d's version and the helper's
last answer. The pages for settings, devices, and Check and Apply build on it.

Every page is made here, with every value escaped, and carries headers that keep it out of
frames, stop other sites' scripts, and keep it out of caches. A form is accepted only from
the Dashboard's own pages: every POST must come with an Origin header naming the Dashboard
(and, from browsers that send it, Sec-Fetch-Site: same-origin). GET never changes anything.

A slow or silent client can't hold it up: each connection's TLS handshake happens in its own
thread, with a time limit, every connection has a time limit, and only so many run at once.
"""

from __future__ import annotations

import html
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
from ok3d.dashboard import helper_link
from ok3d.dashboard.auth import SESSION_TTL, Auth, Paused

# __Host-: browsers accept it only over HTTPS, for this host and every path, so no other site
# or name can set it.
COOKIE = "__Host-ok3d_session"
# Seconds a connection may take for its handshake, and between reads and writes after.
TIMEOUT = 10
# The most connections served at once; the rest are closed straight away.
MAX_CONNECTIONS = 32
# The most of a form that's read. The sign-in form is a few dozen bytes; a settings or devices
# file may be 64 KB, which a browser may send at up to three times that.
MAX_FORM = 4096
MAX_FILE_FORM = 3 * 64 * 1024 + 1024

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
    '<nav><a href="/">Home</a> <a href="/settings">Settings</a> <a href="/devices">Devices</a> '
    '<a href="/keys">Keys</a></nav>'
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
    note = f"<p class=good>{html.escape(message)}</p>" if message else ""
    if not helper_link.alive(config.helper):
        helper = (
            "<p class=bad>The helper isn't running, so Check, Apply, and saving can't happen from "
            "here. On the server: <code>systemctl --user status ok3d-helper</code>.</p>"
        )
    else:
        helper = "<p class=good>The helper is running.</p>"
    apply_note = (
        ""
        if helper_link.can_apply(config.helper)
        else "<p class=muted>Apply turns on once a Check finds no problems, and off again after a save.</p>"
    )
    disabled = "" if helper_link.can_apply(config.helper) else " disabled"
    return (
        f"<section><h2>ok3d {html.escape(__version__)}</h2>{note}{helper}"
        "<p>Check that the server and your settings are ready, then Apply to make the cluster and "
        "deploy, or bring it up to date with your settings.</p>"
        '<form class="inline" method="post" action="/check"><button>Check</button></form> '
        f'<form class="inline" method="post" action="/apply"><button{disabled}>Apply</button></form>'
        f"{apply_note}</section>" + answer_section(config)
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
    if text is None:
        if name == "settings.yaml":
            return (f"<section><h2>{title}</h2>{about}<p class=bad>There's no settings.yaml on the "
                    "server yet. Make it there first, from settings.example.yaml; after that you can "
                    "change it here.</p></section>")  # fmt: skip
        text = "devices: []\n"
    note = f"<p class=bad>{html.escape(message)}</p>" if message else ""
    return (
        f"<section><h2>{title}</h2>{about}{note}"
        f'<form method="post" action="/{title.lower()}">'
        f'<p><textarea name="file" rows="24" spellcheck="false" aria-label="{name}">{html.escape(text)}</textarea></p>'
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
            fields = urllib.parse.parse_qs(body.decode("utf-8", errors="replace"), max_num_fields=10)
        except ValueError:
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
                   name: str | None = None, body: bytes | None = None) -> None:  # fmt: skip
        """Leaves a request for the helper, then sends you Home to watch for the answer, or
        back to the page with what went wrong."""
        if not helper_link.alive(self.config.helper):
            self.send(503, page(title, render(self.config, "The helper isn't running, so nothing was sent."), True))
            return
        try:
            helper_link.send(self.config.state, self.config.helper, action, name, body)
        except helper_link.Busy:
            self.send(409, page(title, render(self.config, "The helper is busy with the last request. "
                                              "Try again when Home shows its answer."), True))  # fmt: skip
            return
        self.redirect(back)

    def post_check(self) -> None:
        self.ask_helper("/", home, "Home", "check")

    def post_apply(self) -> None:
        if not helper_link.can_apply(self.config.helper):
            self.send(409, page("Home", home(self.config, "") + "<p class=bad>Run a Check that finds "
                                "no problems first.</p>", True))  # fmt: skip
            return
        self.ask_helper("/", home, "Home", "apply")

    def post_file(self, name: str, action: str, title: str) -> None:
        def render(config: Config, message: str) -> str:
            return file_page(config, name, message)

        form = self.read_form(MAX_FILE_FORM)
        text = (form or {}).get("file")
        if text is None:
            self.send(400, page(title, render(self.config, "That didn't arrive in one piece. Try again."), True))
            return
        # A browser sends a text box's lines with \r\n; the files use \n.
        data = text.replace("\r\n", "\n").encode("utf-8")
        if not data.endswith(b"\n"):
            data += b"\n"
        if len(data) > helper_link.MAX_FILE:
            self.send(413, page(title, render(self.config, "That's bigger than 64 KB."), True))
            return
        self.ask_helper("/", render, title, action, body=data)

    def post_settings(self) -> None:
        self.post_file("settings.yaml", "save-settings", "Settings")

    def post_devices(self) -> None:
        self.post_file("devices.yaml", "save-devices", "Devices")

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
    "/settings": ("Settings", lambda c, m: file_page(c, "settings.yaml", m)),
    "/devices": ("Devices", lambda c, m: file_page(c, "devices.yaml", m)),
    "/keys": ("Keys", keys_page),
}

# What each form does, by path. Every one needs a session and the Dashboard's own Origin.
ACTIONS: dict[str, Callable[[Handler], None]] = {
    "/check": Handler.post_check,
    "/apply": Handler.post_apply,
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
