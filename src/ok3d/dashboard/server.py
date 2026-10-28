"""The Dashboard's web server: HTTPS only, behind its own sign-in.

This first version has the sign-in and one page, which shows ok3d's version and the helper's
last answer. The pages for settings, devices, and Check and Apply build on it.

Every page is made here, with every value escaped, and carries headers that keep it out of
frames, stop other sites' scripts, and keep it out of caches. A form can only be sent from
the Dashboard's own pages: every POST must come with an Origin header naming the Dashboard,
and the session cookie is never sent with requests from other sites.
"""

from __future__ import annotations

import html
import ssl
import time
import urllib.parse
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ok3d import __version__
from ok3d.dashboard.auth import SESSION_TTL, Auth

COOKIE = "ok3d_session"
# The most of a form that's read. The sign-in form is a few dozen bytes.
MAX_FORM = 4096
# The most of the helper's answer that's read.
MAX_RESULT = 256 * 1024

HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; "
    "frame-ancestors 'none'; base-uri 'none'",
    "Strict-Transport-Security": "max-age=31536000",
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
"""


@dataclass(frozen=True)
class Config:
    state: Path  # <data root>/dashboard, the Dashboard's own folder
    helper: Path  # <data root>/helper, read-only: the helper's answers


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
        f"<header><h1>ok3d</h1>{sign_out}</header><main>{body}</main></html>"
    ).encode()


def read_result(helper: Path) -> tuple[dict[str, str], str] | None:
    """The helper's last answer: its fields, and what ok3d printed. None if there's none."""
    try:
        with (helper / "result").open("rb") as f:
            text = f.read(MAX_RESULT).decode("utf-8", errors="replace")
    except OSError:
        return None
    head, _, output = text.partition("\n\n")
    fields = dict(line.split("=", 1) for line in head.splitlines() if "=" in line)
    return fields, output


def home(config: Config) -> str:
    """The first page: ok3d's version, and the helper's last answer."""
    parts = [
        "<section><h2>ok3d</h2>"
        f"<p>Version {html.escape(__version__)}. The pages for your settings, devices, and Check and "
        "Apply arrive during 0.5.</p></section>"
    ]
    result = read_result(config.helper)
    if result is None:
        parts.append(
            "<section><h2>The helper</h2><p class=muted>No answer from the helper yet. It runs "
            "<code>./ok3d check</code> and <code>./ok3d apply</code> for this page.</p></section>"
        )
    else:
        fields, output = result
        state = fields.get("state", "unknown")
        status = {"finished": "good" if fields.get("exit") == "0" else "bad", "refused": "bad", "failed": "bad"}
        words = {
            "running": "is running",
            "finished": f"finished with exit status {fields.get('exit', '?')}",
            "refused": f"was refused: {fields.get('reason', '')}",
            "failed": f"couldn't run: {fields.get('reason', '')}",
        }
        action = fields.get("action", "a request")
        when = f" at {fields['finished']}" if "finished" in fields else ""
        parts.append(
            "<section><h2>The helper's last answer</h2>"
            f'<p class="{status.get(state, "muted")}">{html.escape(action)} '
            f"{html.escape(words.get(state, state))}{html.escape(when)}.</p>"
            + (f"<pre>{html.escape(output)}</pre>" if output.strip() else "")
            + "</section>"
        )
    return "".join(parts)


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


class Handler(BaseHTTPRequestHandler):
    # Names the server without its Python version, which would only help someone looking for holes.
    def version_string(self) -> str:
        return "ok3d-dashboard"

    # Set on the class by make_server().
    config: Config
    auth: Auth

    def log_message(self, format: str, *args: object) -> None:  # the base class names it format
        # One line a request, without the query string, which could hold anything.
        print(f"{self.address_string()} {self.command} {self.path.split('?')[0]}", flush=True)

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
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        morsel = cookie.get(COOKIE)
        return morsel.value if morsel else None

    def signed_in(self) -> bool:
        return self.auth.valid(self.session())

    def same_origin(self) -> bool:
        """Whether a POST came from one of the Dashboard's own pages."""
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        return bool(origin and host) and origin == f"https://{host}"

    def read_form(self) -> dict[str, str] | None:
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return None
        if not 0 <= length <= MAX_FORM:
            return None
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/x-www-form-urlencoded":
            return None
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        return {k: v[0] for k, v in urllib.parse.parse_qs(body, max_num_fields=10).items()}

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path == "/style.css":
            self.send(200, STYLE, "text/css; charset=utf-8")
        elif path == "/sign-in":
            if self.signed_in():
                self.redirect("/")
            else:
                self.send(200, page("Sign in", sign_in_page()))
        elif path == "/":
            if self.signed_in():
                self.send(200, page("Home", home(self.config), signed_in=True))
            else:
                self.redirect("/sign-in")
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
            form = self.read_form()
            if form is None:
                self.send(400, page("Sign in", sign_in_page("That didn't arrive in one piece. Try again.")))
                return
            if self.auth.locked():
                self.send(429, page("Sign in", sign_in_page("Too many wrong passwords. Wait a minute, then try again.")))
                return
            session = self.auth.sign_in(form.get("password", ""))
            if session is None:
                time.sleep(0.5)  # a little slower, for anyone guessing
                self.send(401, page("Sign in", sign_in_page("That's not the password.")))
                return
            cookie = f"{COOKIE}={session}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}"
            self.redirect("/", {"Set-Cookie": cookie})
        elif path == "/sign-out":
            self.auth.sign_out(self.session())
            self.redirect("/sign-in", {"Set-Cookie": f"{COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0"})
        else:
            self.send(404, page("Not found", "<section><h2>Not found</h2></section>", self.signed_in()))


def make_server(config: Config, host: str, port: int, cert: Path, key: Path) -> ThreadingHTTPServer:
    """The server, with TLS 1.2 or newer and the Dashboard's certificate. It serves nothing
    without TLS."""
    auth = Auth(config.state)
    if auth.ensure():
        print(f"ok3d-dashboard: made a password; it's in {config.state / 'password'}", flush=True)
    handler = type("DashboardHandler", (Handler,), {"config": config, "auth": auth})
    server = ThreadingHTTPServer((host, port), handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    return server
