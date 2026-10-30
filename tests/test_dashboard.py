"""Tests for the Dashboard's web server and sign-in (src/ok3d/dashboard/).

Each test starts the real server, over HTTPS with a throwaway certificate, and talks to it the
way a browser would: pages need a session, the password makes one, forms from other sites
are refused, wrong guesses are limited, and nothing from the helper's answer reaches the page
unescaped.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import http.client
import json
import re
import urllib.parse
import os
import shutil
import socket
import ssl
import stat
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from ok3d import __version__
from ok3d.dashboard import auth as auth_module
from ok3d.dashboard.auth import Auth
from ok3d.dashboard.server import COOKIE, Config, make_server

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs openssl for a test certificate")


@dataclass
class Dashboard:
    port: int
    state: Path
    helper: Path

    @property
    def password(self) -> str:
        return (self.state / "password").read_text().strip()

    def request(self, method: str, path: str, body: str = "", headers: dict[str, str] | None = None
                ) -> http.client.HTTPResponse:  # fmt: skip
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        conn = http.client.HTTPSConnection("127.0.0.1", self.port, context=context, timeout=10)
        conn.request(method, path, body=body.encode() or None, headers=headers or {})
        response = conn.getresponse()
        response.read_body = response.read()  # type: ignore[attr-defined]
        conn.close()
        return response

    def post(self, path: str, body: str = "", origin: str | None = "same", session: str | None = None
             ) -> http.client.HTTPResponse:  # fmt: skip
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if origin == "same":
            headers["Origin"] = f"https://127.0.0.1:{self.port}"
        elif origin:
            headers["Origin"] = origin
        if session:
            headers["Cookie"] = f"{COOKIE}={session}"
        return self.request("POST", path, body, headers)

    def get(self, path: str, session: str | None = None) -> http.client.HTTPResponse:
        return self.request("GET", path, headers={"Cookie": f"{COOKIE}={session}"} if session else {})

    def sign_in(self) -> str:
        response = self.post("/sign-in", f"password={self.password}")
        assert response.status == 303
        cookie = response.getheader("Set-Cookie") or ""
        return cookie.split(";")[0].split("=", 1)[1]


def body(response: http.client.HTTPResponse) -> str:
    return response.read_body.decode()  # type: ignore[attr-defined, no-any-return]


@pytest.fixture
def dash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Dashboard]:
    monkeypatch.setattr(auth_module, "SCRYPT", {"n": 2**10, "r": 8, "p": 1})  # quicker for tests
    monkeypatch.setattr("ok3d.dashboard.server.time.sleep", lambda _s: None)
    state, helper = tmp_path / "state", tmp_path / "helper"
    state.mkdir()
    helper.mkdir()
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
         "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=localhost"],
        check=True, capture_output=True,
    )  # fmt: skip
    server = make_server(Config(state, helper), "127.0.0.1", 0, cert, key)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield Dashboard(server.server_address[1], state, helper)
    server.shutdown()
    server.server_close()


def test_it_makes_a_password_readable_only_by_you(dash: Dashboard) -> None:
    assert len(dash.password) == 19
    for name in ("password", "password.json"):
        assert stat.S_IMODE((dash.state / name).stat().st_mode) == 0o600
    record = json.loads((dash.state / "password.json").read_text())
    assert dash.password not in json.dumps(record)


def test_the_password_stays_the_same_across_restarts(tmp_path: Path) -> None:
    first = Auth(tmp_path)
    assert first.ensure()
    password = (tmp_path / "password").read_text()
    assert not Auth(tmp_path).ensure()
    assert (tmp_path / "password").read_text() == password


def test_a_damaged_record_gets_a_new_password(tmp_path: Path) -> None:
    (tmp_path / "password.json").write_text("{not json")
    assert Auth(tmp_path).ensure()
    assert json.loads((tmp_path / "password.json").read_text())["hash"]


def test_pages_need_a_session(dash: Dashboard) -> None:
    response = dash.get("/")
    assert response.status == 303
    assert response.getheader("Location") == "/sign-in"
    assert dash.get("/", session="made-up").status == 303


def test_the_password_signs_you_in_with_a_safe_cookie(dash: Dashboard) -> None:
    response = dash.post("/sign-in", f"password={dash.password}")
    assert response.status == 303
    cookie = response.getheader("Set-Cookie") or ""
    for flag in ("Secure", "HttpOnly", "SameSite=Strict", "Path=/"):
        assert flag in cookie
    session = cookie.split(";")[0].split("=", 1)[1]
    home = dash.get("/", session)
    assert home.status == 200
    assert f"ok3d {__version__}" in body(home)


def test_a_wrong_password_signs_nobody_in(dash: Dashboard) -> None:
    response = dash.post("/sign-in", "password=wrong")
    assert response.status == 401
    assert response.getheader("Set-Cookie") is None
    assert "not the password" in body(response)


def test_too_many_wrong_passwords_pause_sign_in_even_for_the_right_one(dash: Dashboard) -> None:
    for _ in range(auth_module.MAX_FAILURES):
        assert dash.post("/sign-in", "password=wrong").status == 401
    assert dash.post("/sign-in", f"password={dash.password}").status == 429


def test_the_pause_ends(tmp_path: Path) -> None:
    auth = Auth(tmp_path)
    auth.ensure()
    for _ in range(auth_module.MAX_FAILURES):
        assert auth.sign_in("wrong", "192.0.2.9", now=1000.0) is None
    password = (tmp_path / "password").read_text().strip()
    with pytest.raises(auth_module.Paused):
        auth.sign_in(password, "192.0.2.9", now=1000.0 + auth_module.LOCKOUT - 1)
    assert auth.sign_in(password, "192.0.2.9", now=1000.0 + auth_module.LOCKOUT + 1) is not None


def test_one_device_guessing_doesnt_lock_out_another(tmp_path: Path) -> None:
    auth = Auth(tmp_path)
    auth.ensure()
    for _ in range(auth_module.MAX_FAILURES):
        auth.sign_in("wrong", "192.0.2.66", now=1000.0)
    password = (tmp_path / "password").read_text().strip()
    with pytest.raises(auth_module.Paused):
        auth.sign_in(password, "192.0.2.66", now=1001.0)
    assert auth.sign_in(password, "192.0.2.10", now=1001.0) is not None


def test_guesses_from_many_addresses_pause_everyone(tmp_path: Path) -> None:
    auth = Auth(tmp_path)
    auth.ensure()
    for n in range(auth_module.GLOBAL_FAILURES):
        auth.sign_in("wrong", f"192.0.2.{n % 200}", now=1000.0)
    password = (tmp_path / "password").read_text().strip()
    with pytest.raises(auth_module.Paused):
        auth.sign_in(password, "192.0.2.250", now=1001.0)
    assert auth.sign_in(password, "192.0.2.250", now=1000.0 + auth_module.LOCKOUT + 1) is not None


def test_guesses_sent_together_still_count_one_by_one(dash: Dashboard) -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(lambda _: dash.post("/sign-in", "password=wrong").status, range(20)))
    assert codes.count(401) == auth_module.MAX_FAILURES
    assert codes.count(429) == 20 - auth_module.MAX_FAILURES


def test_the_addresses_remembered_are_capped(tmp_path: Path) -> None:
    auth = Auth(tmp_path)
    auth.ensure()
    for n in range(auth_module.MAX_CLIENTS + 50):
        auth._count_failure(f"client-{n}", now=1000.0 + n * 10)
    assert len(auth.failures) <= auth_module.MAX_CLIENTS


def test_a_session_ends(tmp_path: Path) -> None:
    auth = Auth(tmp_path)
    auth.ensure()
    session = auth.sign_in((tmp_path / "password").read_text().strip(), now=0.0)
    assert auth.valid(session, now=auth_module.SESSION_TTL - 1)
    assert not auth.valid(session, now=auth_module.SESSION_TTL + 1)


@pytest.mark.parametrize("origin", [None, "https://evil.example", "http://127.0.0.1", "null"])
def test_a_form_from_anywhere_else_is_refused(dash: Dashboard, origin: str | None) -> None:
    response = dash.post("/sign-in", f"password={dash.password}", origin=origin)
    assert response.status == 403
    assert response.getheader("Set-Cookie") is None


def test_signing_out_ends_the_session(dash: Dashboard) -> None:
    session = dash.sign_in()
    assert dash.post("/sign-out", session=session).status == 303
    assert dash.get("/", session).status == 303


def test_a_form_too_big_or_of_the_wrong_kind_is_refused(dash: Dashboard) -> None:
    big = dash.post("/sign-in", "password=" + "x" * 5000)
    assert big.status == 400
    json_body = dash.request("POST", "/sign-in", '{"password": "x"}', {
        "Content-Type": "application/json", "Origin": f"https://127.0.0.1:{dash.port}"})  # fmt: skip
    assert json_body.status == 400


def test_every_page_carries_the_safety_headers(dash: Dashboard) -> None:
    for response in (dash.get("/sign-in"), dash.get("/nowhere"), dash.get("/", dash.sign_in())):
        csp = response.getheader("Content-Security-Policy") or ""
        assert "default-src 'none'" in csp
        assert "frame-ancestors 'none'" in csp
        assert response.getheader("X-Content-Type-Options") == "nosniff"
        assert response.getheader("Cache-Control") == "no-store"
        # Not no-referrer: then a browser sends "Origin: null" on a form, and same_origin()
        # refuses every one (the screenshots found this; curl doesn't do it).
        assert response.getheader("Referrer-Policy") == "same-origin"
        # No HSTS: it would cover every other web page on the server's name, on every port.
        assert response.getheader("Strict-Transport-Security") is None
        assert response.getheader("Server") == "ok3d-dashboard"


def test_the_home_page_shows_the_helpers_last_answer_escaped(dash: Dashboard) -> None:
    (dash.helper / "result").write_text(
        "id=3f9a0c51d2e8b746\naction=check\nstate=finished\nexit=1\nfinished=2026-10-28T18:05:12Z\n\n"
        "FAIL  <script>alert(1)</script> & more\n"
    )
    page = body(dash.get("/", dash.sign_in()))
    assert "check finished with exit status 1 at 2026-10-28T18:05:12Z." in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; more" in page
    assert "<script>" not in page


def test_the_home_page_without_an_answer(dash: Dashboard) -> None:
    assert "None yet." in body(dash.get("/", dash.sign_in()))


def test_plain_http_gets_nothing(dash: Dashboard) -> None:
    conn = http.client.HTTPConnection("127.0.0.1", dash.port, timeout=5)
    with pytest.raises((http.client.HTTPException, ConnectionError, OSError)):
        conn.request("GET", "/")
        conn.getresponse()
    conn.close()


def test_it_wont_start_without_a_certificate(tmp_path: Path) -> None:
    from ok3d.dashboard.__main__ import main

    with pytest.raises(SystemExit, match="HTTPS only"):
        main(["--state", str(tmp_path), "--helper", str(tmp_path), "--cert", str(tmp_path / "no.crt"),
              "--key", str(tmp_path / "no.key")])  # fmt: skip


def test_a_silent_connection_doesnt_hold_up_anyone_else(dash: Dashboard) -> None:
    # A client that connects and never starts TLS.
    idle = socket.create_connection(("127.0.0.1", dash.port))
    try:
        assert dash.get("/sign-in").status == 200
    finally:
        idle.close()


def test_connections_beyond_the_limit_are_closed(dash: Dashboard, monkeypatch: pytest.MonkeyPatch) -> None:
    import ok3d.dashboard.server as server_module

    idle = [socket.create_connection(("127.0.0.1", dash.port)) for _ in range(server_module.MAX_CONNECTIONS)]
    try:
        time.sleep(0.3)
        extra = socket.create_connection(("127.0.0.1", dash.port))
        extra.settimeout(5)
        assert extra.recv(1) == b""  # closed straight away
        extra.close()
    finally:
        for s in idle:
            s.close()
    # Once they've gone, it serves again.
    for _ in range(50):
        try:
            if dash.get("/sign-in").status == 200:
                break
        except OSError:
            pass
        time.sleep(0.1)
    else:
        pytest.fail("it didn't serve again after the idle connections closed")


@pytest.mark.parametrize("where", ["handshake", "headers"])
def test_a_slow_request_doesnt_keep_its_thread(dash: Dashboard, monkeypatch: pytest.MonkeyPatch,
                                               capsys: pytest.CaptureFixture[str], where: str) -> None:  # fmt: skip
    # A byte at a time, each well within the limit on one read, but never finishing.
    import ok3d.dashboard.server as server_module

    monkeypatch.setattr(server_module, "REQUEST_TIME", 1)
    raw = socket.create_connection(("127.0.0.1", dash.port))
    conn: socket.socket = raw
    if where == "headers":
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        conn = context.wrap_socket(raw)
    # A TLS record that says 16 KB is coming, or a request line, then a byte at a time.
    drip = b"\x16\x03\x01\x40\x00" + b"\x00" * 500 if where == "handshake" else b"GET / HTTP/1.0\r\nX-Slow: " + b"x" * 500
    started = time.monotonic()
    closed = False
    try:
        for byte in drip:
            conn.sendall(bytes([byte]))
            conn.settimeout(0.3)
            try:
                if conn.recv(1) == b"":
                    closed = True
                    break
            except TimeoutError:
                pass
            if time.monotonic() - started > 8:
                break
    except OSError:
        closed = True
    try:
        assert closed
        assert time.monotonic() - started < 5
        # The server's thread gave up too, not just the client's end: it says so, while this
        # end is still open (closing it would end the server's read anyway). The fixture makes
        # time.sleep do nothing, so this waits another way.
        printed = ""
        for _ in range(30):
            printed += capsys.readouterr().out
            if "connection dropped" in printed:
                break
            threading.Event().wait(0.1)
        assert "connection dropped" in printed
    finally:
        conn.close()


def test_a_timer_that_wont_start_doesnt_lose_a_connection(dash: Dashboard, monkeypatch: pytest.MonkeyPatch) -> None:
    # Short of memory or processes, a thread may not start. Each connection that hit that would
    # have kept its place among the MAX_CONNECTIONS for good.
    import ok3d.dashboard.server as server_module

    failures = {"left": server_module.MAX_CONNECTIONS}

    class Unstartable(threading.Timer):
        def start(self) -> None:
            if failures["left"] > 0:
                failures["left"] -= 1
                raise RuntimeError("can't start new thread")
            super().start()

    monkeypatch.setattr(threading, "Timer", Unstartable)  # the module the server uses too
    while failures["left"] > 0:
        with pytest.raises((http.client.HTTPException, OSError)):
            dash.get("/sign-in")
    assert dash.get("/sign-in").status == 200


def test_another_apps_odd_cookie_doesnt_sign_you_out(dash: Dashboard) -> None:
    session = dash.sign_in()
    response = dash.request("GET", "/", headers={"Cookie": f'a={{"x":1}}; {COOKIE}={session}; b=2'})
    assert response.status == 200


def test_the_cookie_is_host_only(dash: Dashboard) -> None:
    cookie = dash.post("/sign-in", f"password={dash.password}").getheader("Set-Cookie") or ""
    assert cookie.startswith("__Host-")
    assert "Domain" not in cookie


def test_a_form_a_browser_marks_cross_site_is_refused(dash: Dashboard) -> None:
    response = dash.request("POST", "/sign-in", f"password={dash.password}", {
        "Content-Type": "application/x-www-form-urlencoded", "Origin": f"https://127.0.0.1:{dash.port}",
        "Sec-Fetch-Site": "same-site"})  # fmt: skip
    assert response.status == 403


def test_a_form_with_too_many_fields_gets_an_answer(dash: Dashboard) -> None:
    assert dash.post("/sign-in", "&".join(f"f{n}=x" for n in range(20))).status == 400


def test_a_form_shorter_than_it_says_doesnt_keep_its_thread(dash: Dashboard, monkeypatch: pytest.MonkeyPatch) -> None:
    from ok3d.dashboard import server as server_module

    monkeypatch.setattr(server_module.Handler, "timeout", 1)
    started = time.monotonic()
    with pytest.raises((http.client.HTTPException, OSError)):
        dash.request("POST", "/sign-in", "password=x", {
            "Content-Type": "application/x-www-form-urlencoded", "Origin": f"https://127.0.0.1:{dash.port}",
            "Content-Length": "100"})  # fmt: skip
    assert time.monotonic() - started < 5


def test_a_request_too_long_gets_an_answer(dash: Dashboard) -> None:
    assert dash.get("/" + "x" * 70000).status == 414


def test_control_characters_never_reach_the_log(dash: Dashboard, capsys: pytest.CaptureFixture[str]) -> None:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with socket.create_connection(("127.0.0.1", dash.port)) as raw, context.wrap_socket(raw) as tls:
        tls.sendall(b"GET /\x1b[31mred HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        while tls.recv(4096):
            pass
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert "\\x1b[31mred" in out


def test_a_password_record_it_cant_read_stops_it_rather_than_replacing_it(tmp_path: Path) -> None:
    auth = Auth(tmp_path)
    auth.ensure()
    password = (tmp_path / "password").read_text()
    (tmp_path / "password.json").chmod(0)
    try:
        if os.access(tmp_path / "password.json", os.R_OK):
            pytest.skip("running as root, which reads anything")
        with pytest.raises(SystemExit, match="can't read"):
            Auth(tmp_path).ensure()
    finally:
        (tmp_path / "password.json").chmod(0o600)
    assert (tmp_path / "password").read_text() == password


def test_a_folder_it_cant_write_stops_it_with_a_clear_message(tmp_path: Path) -> None:
    tmp_path.chmod(0o500)
    try:
        if os.access(tmp_path, os.W_OK):
            pytest.skip("running as root, which writes anywhere")
        with pytest.raises(SystemExit, match="can't write its password"):
            Auth(tmp_path).ensure()
    finally:
        tmp_path.chmod(0o700)


# The pages that ask the helper for something. The helper itself isn't running here: these
# check what the Dashboard writes to its outbox, and what it shows from the helper's folder.


def alive(dash: Dashboard) -> None:
    from datetime import UTC, datetime

    (dash.helper / "alive").write_text(datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")


def outbox(dash: Dashboard) -> bytes:
    return (dash.state / "outbox" / "request").read_bytes()


@pytest.fixture
def ready(dash: Dashboard) -> Dashboard:
    (dash.state / "outbox").mkdir()
    alive(dash)
    return dash


def head(data: bytes) -> dict[str, str]:
    return dict(line.split("=", 1) for line in data.partition(b"\n\n")[0].decode().splitlines())


def test_check_leaves_a_request_for_the_helper(ready: Dashboard) -> None:
    response = ready.post("/check", session=ready.sign_in())
    assert response.status == 303
    request = outbox(ready)
    fields = head(request)
    assert fields["action"] == "check"
    assert re.fullmatch(r"[0-9a-f]{32}", fields["id"])
    assert request == f"id={fields['id']}\naction=check\n".encode()
    assert stat.S_IMODE((ready.state / "outbox" / "request").stat().st_mode) == 0o600


def test_nothing_is_sent_without_a_session_or_from_another_site(ready: Dashboard) -> None:
    assert ready.post("/check").status == 303  # to sign in
    assert ready.post("/check", origin="https://evil.example", session=ready.sign_in()).status == 403
    assert not (ready.state / "outbox" / "request").exists()


def test_one_request_at_a_time(ready: Dashboard) -> None:
    session = ready.sign_in()
    ready.post("/check", session=session)
    first = outbox(ready)
    assert ready.post("/check", session=session).status == 409
    assert outbox(ready) == first
    (ready.state / "outbox" / "request").unlink()
    (ready.helper / "result").write_text("id=x\naction=check\nstate=running\n\n")
    assert ready.post("/check", session=session).status == 409


def test_nothing_is_sent_while_the_helper_isnt_running(ready: Dashboard) -> None:
    (ready.helper / "alive").write_text("2020-01-01T00:00:00Z\n")
    session = ready.sign_in()
    assert "The helper isn't running" in body(ready.get("/", session))
    assert ready.post("/check", session=session).status == 503
    assert not (ready.state / "outbox" / "request").exists()


def test_apply_waits_for_a_check_that_passed(ready: Dashboard) -> None:
    session = ready.sign_in()
    assert "<button disabled>Apply</button>" in body(ready.get("/", session))
    assert ready.post("/apply", session=session).status == 409
    ready.post("/check", session=session)
    sent = head(outbox(ready))["id"]
    (ready.state / "outbox" / "request").unlink()
    (ready.helper / "result").write_text(f"id={sent}\naction=check\nstate=finished\nexit=1\n\nFAIL  x\n")
    assert ready.post("/apply", session=session).status == 409
    (ready.helper / "result").write_text(f"id={sent}\naction=check\nstate=finished\nexit=0\n\nReady.\n")
    (ready.helper / "apply-plan").write_text("checked=2026-10-30T09:00:00Z\nstate=none\nother=0\n")
    assert "<button>Apply</button>" in body(ready.get("/", session))
    assert ready.post("/apply", session=session).status == 303
    assert head(outbox(ready))["action"] == "apply"
    # Anything sent since the Check turns it off again, even before its answer arrives.
    (ready.state / "outbox" / "request").unlink()
    assert (ready.state / "last-sent").read_text().split()[0] != sent
    (ready.helper / "result").write_text(f"id={sent}\naction=check\nstate=finished\nexit=0\n\nReady.\n")
    assert ready.post("/apply", session=session).status == 409


def test_the_settings_page_shows_yours_and_saves_a_change(ready: Dashboard) -> None:
    (ready.helper / "current-settings.yaml").write_text("settingsVersion: 1\nhost:\n  dataRoot: /srv/ok3d\n# <b>x</b>\n")
    session = ready.sign_in()
    shown = body(ready.get("/settings", session))
    assert "dataRoot: /srv/ok3d" in shown
    assert "&lt;b&gt;x&lt;/b&gt;" in shown
    new = "settingsVersion: 1\r\nmetrics:\r\n  retention: 60d"
    shown_copy = (ready.helper / "current-settings.yaml").read_text()
    base = hashlib.sha256(shown_copy.encode()).hexdigest()
    assert f'name="base" value="{base}"' in shown
    response = ready.post("/settings", f"base={base}&file=" + urllib.parse.quote(new), session=session)
    assert response.status == 303
    request = outbox(ready)
    assert head(request)["action"] == "save-settings"
    assert request.partition(b"\n\n")[2] == b"settingsVersion: 1\nmetrics:\n  retention: 60d\n"
    assert head(request)["base"] == base


def test_settings_cant_be_saved_before_there_are_any(ready: Dashboard) -> None:
    assert "There's no settings.yaml on the server yet" in body(ready.get("/settings", ready.sign_in()))


def test_devices_are_saved_the_same_way(ready: Dashboard) -> None:
    session = ready.sign_in()
    assert "devices: []" in body(ready.get("/devices", session))
    assert 'name="base" value="none"' in body(ready.get("/devices", session))
    ready.post("/devices", "base=none&file=" + urllib.parse.quote("devices: []\n"), session=session)
    assert head(outbox(ready))["action"] == "save-devices"
    assert head(outbox(ready))["base"] == "none"


def test_a_file_too_big_isnt_sent(ready: Dashboard) -> None:
    response = ready.post("/devices", "base=none&file=" + "x" * (65 * 1024), session=ready.sign_in())
    assert response.status == 413
    lines = ready.post("/devices", "base=none&file=" + "%0D%0A" * 70000, session=ready.sign_in())
    assert lines.status == 413
    assert not (ready.state / "outbox" / "request").exists()


def raw_post(dash: Dashboard, path: str, length: int, origin: str | None = None, session: str = "",
             kind: str = "application/x-www-form-urlencoded") -> ssl.SSLSocket:  # fmt: skip
    """A TLS connection that has sent a POST's headers, saying the body is length bytes, and none of it."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    lines = [f"POST {path} HTTP/1.1", f"Host: 127.0.0.1:{dash.port}",
             f"Origin: {origin or f'https://127.0.0.1:{dash.port}'}",
             f"Content-Type: {kind}", f"Content-Length: {length}"]  # fmt: skip
    if session:
        lines.append(f"Cookie: {COOKIE}={session}")
    conn = context.wrap_socket(socket.create_connection(("127.0.0.1", dash.port)))
    conn.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
    return conn


def answer_of(conn: ssl.SSLSocket) -> bytes:
    conn.settimeout(10)
    answer = b""
    while chunk := conn.recv(65536):
        answer += chunk
    conn.close()
    return answer


# Every refusal that comes before a form is used: a file too big, a form too big or of the
# wrong kind, no session, a form from elsewhere, and a page that isn't there.
FORM = "application/x-www-form-urlencoded"
REFUSALS = {
    "a file too big": ("/devices", 420_000, None, True, FORM, 413),
    "a form too big": ("/sign-in", 420_000, None, False, FORM, 400),
    "a form of the wrong kind": ("/sign-in", 3000, None, False, "text/plain", 400),
    "no session": ("/devices", 300_000, None, False, FORM, 303),
    "from elsewhere": ("/devices", 300_000, "https://example.com", True, FORM, 403),
    "not there": ("/nowhere", 300_000, None, True, FORM, 404),
}


@pytest.mark.parametrize(("path", "size", "origin", "signed_in", "kind", "status"), REFUSALS.values(),
                         ids=REFUSALS.keys())  # fmt: skip
def test_a_refused_form_is_read_before_its_refused(ready: Dashboard, path: str, size: int, origin: str | None,
                                                   signed_in: bool, kind: str, status: int) -> None:  # fmt: skip
    # Refused straight away and closed, the browser would still be sending, and would show a
    # reset connection instead of the refusal. So the server reads the body first.
    conn = raw_post(ready, path, size, origin, ready.sign_in() if signed_in else "", kind)
    conn.settimeout(1)
    with pytest.raises(TimeoutError):
        conn.recv(1)  # nothing yet: it's waiting for the body
    conn.sendall(b"x" * size)
    assert answer_of(conn).startswith(f"HTTP/1.0 {status} ".encode())


def test_a_body_too_big_to_read_is_refused_straight_away(ready: Dashboard) -> None:
    from ok3d.dashboard.server import MAX_DISCARD

    conn = raw_post(ready, "/devices", MAX_DISCARD + 1, session=ready.sign_in())
    assert answer_of(conn).startswith(b"HTTP/1.0 413 ")


def test_a_negative_length_gets_an_answer(dash: Dashboard) -> None:
    assert answer_of(raw_post(dash, "/sign-in", -5)).startswith(b"HTTP/1.0 400 ")


# A form sent slowly: one to be thrown away (too big), and one within the limit, to be read.
@pytest.mark.parametrize("size", [100_000, 4000], ids=["refused", "read"])
def test_a_slow_body_doesnt_keep_its_thread(ready: Dashboard, monkeypatch: pytest.MonkeyPatch, size: int) -> None:
    from ok3d.dashboard import server as server_module

    monkeypatch.setattr(server_module, "BODY_TIME", 1)
    conn = raw_post(ready, "/sign-in", size)
    started = time.monotonic()
    answer = b""
    while time.monotonic() - started < 8:
        try:
            conn.sendall(b"x" * 10)  # a little at a time, quicker than the timeout between reads
            conn.settimeout(0.3)
            answer = conn.recv(65536)
            break
        except TimeoutError:
            continue
        except OSError:
            break
    conn.close()
    assert time.monotonic() - started < 5
    assert answer == b"" or answer.startswith(b"HTTP/1.0 400 ")


def test_keys_show_only_whether_each_is_set(ready: Dashboard) -> None:
    (ready.helper / "env-set").write_text("UNIFI_API_KEY\nOK3D_ADMIN_PASSWORD\n")
    shown = body(ready.get("/keys", ready.sign_in()))
    assert "<code>UNIFI_API_KEY</code> <span class=good>set</span>" in shown
    assert "<code>NTFY_TOPIC</code> <span class=muted>not set</span>" in shown
    assert "<code>OK3D_ADMIN_PASSWORD</code> (set)" in shown
    assert 'name="value" value' not in shown


def test_a_key_is_sent_to_the_helper(ready: Dashboard) -> None:
    response = ready.post("/keys", "name=NTFY_TOPIC&value=ok3d-7f3k9q2m8x", session=ready.sign_in())
    assert response.status == 303
    request = outbox(ready)
    assert head(request)["action"] == "set-env"
    assert head(request)["name"] == "NTFY_TOPIC"
    assert request.partition(b"\n\n")[2] == b"ok3d-7f3k9q2m8x"


@pytest.mark.parametrize("form", ["name=OK3D_ADMIN_PASSWORD&value=x", "name=PATH&value=x",
                                  "name=NTFY_TOPIC&value=a%20b", "name=NTFY_TOPIC&value=%24(reboot)"])  # fmt: skip
def test_a_key_the_helper_would_refuse_isnt_sent(ready: Dashboard, form: str) -> None:
    assert ready.post("/keys", form, session=ready.sign_in()).status == 400
    assert not (ready.state / "outbox" / "request").exists()


def test_a_value_is_never_shown_back(ready: Dashboard) -> None:
    session = ready.sign_in()
    response = ready.post("/keys", "name=NTFY_TOPIC&value=a%20b", session=session)
    assert "a b" not in body(response)


def test_the_dashboards_own_addresses_when_given(tmp_path: Path, dash: Dashboard) -> None:
    from ok3d.dashboard import server as server_module

    handler_config = Config(dash.state, dash.helper, origins=("https://my-server.lan:8444",))
    handler = server_module.Handler
    assert handler_config.origins == ("https://my-server.lan:8444",)
    # The running server was made without, so its own Host counts; one made with them
    # accepts only those (checked through same_origin directly).
    fake = handler.__new__(handler)
    fake.config = handler_config
    fake.headers = http.client.HTTPMessage()
    fake.headers["Origin"] = f"https://127.0.0.1:{dash.port}"
    fake.headers["Host"] = f"127.0.0.1:{dash.port}"
    assert not fake.same_origin()
    fake.headers.replace_header("Origin", "https://my-server.lan:8444")
    assert fake.same_origin()


def test_the_dashboard_and_the_helper_agree_on_what_may_be_sent() -> None:
    from ok3d import helper
    from ok3d.dashboard import helper_link, server

    assert helper_link.ENV_NAMES == helper.ENV_NAMES
    assert tuple(name for name, _ in server.KEY_ABOUT) == helper.ENV_NAMES
    assert helper_link.ENV_VALUE.pattern == helper.ENV_VALUE.pattern
    assert helper_link.MAX_FILE == helper.MAX_FILE
    assert helper_link.VERSION.pattern == helper.VERSION.pattern



def test_a_passed_check_from_before_doesnt_turn_apply_on(ready: Dashboard) -> None:
    # A Check this Dashboard didn't send (or sent before something else) doesn't count.
    (ready.helper / "result").write_text("id=0123456789abcdef\naction=check\nstate=finished\nexit=0\n\n")
    assert ready.post("/apply", session=ready.sign_in()).status == 409


def test_busy_until_the_answer_to_our_last_request_arrives(ready: Dashboard) -> None:
    session = ready.sign_in()
    (ready.helper / "result").write_text("id=0123456789abcdef\naction=check\nstate=finished\nexit=0\n\n")
    ready.post("/check", session=session)
    sent = head(outbox(ready))["id"]
    (ready.state / "outbox" / "request").unlink()  # taken, but not answered yet
    assert ready.post("/check", session=session).status == 409
    (ready.helper / "result").write_text(f"id={sent}\naction=check\nstate=finished\nexit=0\n\n")
    assert ready.post("/check", session=session).status == 303


def test_a_running_answer_from_a_helper_that_stopped_doesnt_block_forever(ready: Dashboard) -> None:
    (ready.helper / "result").write_text("id=0123456789abcdef\naction=apply\nstate=running\n\n")
    (ready.helper / "alive").write_text("2020-01-01T00:00:00Z\n")
    from ok3d.dashboard import helper_link

    assert not helper_link.busy(ready.state, ready.helper)


def test_two_tabs_sending_at_once_send_one(ready: Dashboard) -> None:
    session = ready.sign_in()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(lambda _: ready.post("/check", session=session).status, range(8)))
    assert codes.count(303) == 1
    assert codes.count(409) == 7


def test_no_outbox_gets_an_answer(dash: Dashboard) -> None:
    alive(dash)
    response = dash.post("/check", session=dash.sign_in())
    assert response.status == 503
    assert "write its outbox" in body(response)


def test_a_file_starting_with_a_blank_line_keeps_it(ready: Dashboard) -> None:
    (ready.helper / "current-devices.yaml").write_text("\ndevices: []\n")
    assert '">\n\ndevices: []' in body(ready.get("/devices", ready.sign_in()))


def test_a_form_that_isnt_utf8_is_refused(ready: Dashboard) -> None:
    response = ready.post("/devices", "base=none&file=%FF%FE", session=ready.sign_in())
    assert response.status == 400
    assert not (ready.state / "outbox" / "request").exists()


@pytest.mark.parametrize("path", ["/check", "/apply", "/setup", "/settings", "/devices", "/keys"])
def test_every_form_refuses_a_cross_site_fetch(ready: Dashboard, path: str) -> None:
    response = ready.request("POST", path, "name=NTFY_TOPIC&value=x", {
        "Content-Type": "application/x-www-form-urlencoded", "Origin": f"https://127.0.0.1:{ready.port}",
        "Sec-Fetch-Site": "cross-site", "Cookie": f"{COOKIE}={ready.sign_in()}"})  # fmt: skip
    assert response.status == 403


# The Setup page: ready-made setups and switches, each saved as a whole settings.yaml through
# the helper, like a save from the Settings page. Home's list of what's left, and What's next.

SETTINGS = "settingsVersion: 1\nhost:\n  dataRoot: /srv/ok3d\n"


def settings_are(dash: Dashboard, text: str) -> str:
    """Gives the helper's copy of settings.yaml this text, and returns the base a page sends."""
    (dash.helper / "current-settings.yaml").write_text(text)
    return hashlib.sha256(text.encode()).hexdigest()


def test_the_setup_page_offers_whats_ready_and_says_when_the_rest_comes(ready: Dashboard) -> None:
    settings_are(ready, SETTINGS)
    shown = body(ready.get("/setup", ready.sign_in()))
    for card in ("Basic NOC", "Network NOC", "NOC with logs", "NOC with agents"):
        assert card in shown
    assert "Comes in 0.6." in shown and "Comes in 0.9." in shown
    # Basic is what the settings say now; Network needs UniFi's address first.
    assert "Your setup now." in shown
    assert "unifi.url, in settings.yaml on the server" in shown
    assert "<code>alerts.ntfy.enabled: false</code>" in shown


def test_a_switch_is_saved_through_the_helper(ready: Dashboard) -> None:
    base = settings_are(ready, SETTINGS)
    response = ready.post("/setup", f"base={base}&switch=alerts.ntfy.enabled&on=true", session=ready.sign_in())
    assert response.status == 303
    request = outbox(ready)
    assert head(request)["action"] == "save-settings"
    assert head(request)["base"] == base
    assert request.partition(b"\n\n")[2] == (SETTINGS + "alerts:\n  ntfy:\n    enabled: true\n").encode()


def test_a_card_sets_its_modules(ready: Dashboard) -> None:
    base = settings_are(ready, SETTINGS + "unifi:\n  url: https://192.168.1.1\n")
    assert ready.post("/setup", f"base={base}&card=network", session=ready.sign_in()).status == 303
    assert outbox(ready).partition(b"\n\n")[2].endswith(b"modules:\n  unifi: true\n")


def test_a_card_or_switch_that_needs_something_first_isnt_sent(ready: Dashboard) -> None:
    base = settings_are(ready, SETTINGS)
    session = ready.sign_in()
    response = ready.post("/setup", f"base={base}&card=network", session=session)
    assert response.status == 400
    assert "unifi.url" in body(response)
    assert ready.post("/setup", f"base={base}&switch=modules.unifi&on=true", session=session).status == 400
    assert not (ready.state / "outbox" / "request").exists()


@pytest.mark.parametrize("form", [
    "switch=modules.agents&on=true",  # set only on the server
    "switch=modules.mesh&on=false",
    "switch=modules.plex&on=true",  # not in this release
    "switch=alerts.ntfy.server&on=true",  # not a switch
    "switch=alerts.ntfy.enabled&on=yes",
    "card=agents",
    "card=everything",
    "",
])  # fmt: skip
def test_what_the_setup_page_cant_change_isnt_sent(ready: Dashboard, form: str) -> None:
    base = settings_are(ready, SETTINGS)
    response = ready.post("/setup", f"base={base}&{form}", session=ready.sign_in())
    assert response.status == 400
    assert not (ready.state / "outbox" / "request").exists()


def test_settings_changed_since_the_page_was_shown_arent_overwritten(ready: Dashboard) -> None:
    base = settings_are(ready, SETTINGS)
    settings_are(ready, SETTINGS + "metrics:\n  retention: 60d\n")
    response = ready.post("/setup", f"base={base}&switch=alerts.ntfy.enabled&on=true", session=ready.sign_in())
    assert response.status == 409
    assert not (ready.state / "outbox" / "request").exists()


def test_settings_in_a_shape_it_cant_follow_are_left_to_the_settings_page(ready: Dashboard) -> None:
    base = settings_are(ready, SETTINGS + "alerts: {ntfy: {enabled: false}}\n")
    session = ready.sign_in()
    assert "can&#x27;t change: change it on the Settings page" in body(ready.get("/setup", session))
    response = ready.post("/setup", f"base={base}&switch=alerts.ntfy.enabled&on=true", session=session)
    assert response.status == 400
    assert "Change it on the Settings page" in body(response)
    assert not (ready.state / "outbox" / "request").exists()


def test_a_switch_already_set_sends_nothing(ready: Dashboard) -> None:
    base = settings_are(ready, SETTINGS + "alerts:\n  ntfy:\n    enabled: true\n")
    response = ready.post("/setup", f"base={base}&switch=alerts.ntfy.enabled&on=true", session=ready.sign_in())
    assert "Your settings say that already." in body(response)
    assert not (ready.state / "outbox" / "request").exists()


def test_home_lists_whats_left(ready: Dashboard) -> None:
    settings_are(ready, SETTINGS + "unifi:\n  url: https://192.168.1.1\nmodules:\n  unifi: true\n")
    session = ready.sign_in()
    shown = body(ready.get("/", session))
    assert "UniFi is on, and needs <code>UNIFI_API_KEY</code>: set it on the Keys page." in shown
    assert "Alerts go nowhere yet" in shown
    assert "There are no devices to watch yet" in shown
    (ready.helper / "env-set").write_text("UNIFI_API_KEY\nNTFY_TOPIC\n")
    settings_are(ready, SETTINGS + "unifi:\n  url: https://192.168.1.1\nmodules:\n  unifi: true\n"
                 "alerts:\n  ntfy:\n    enabled: true\n  deadman:\n    enabled: true\n")  # fmt: skip
    (ready.helper / "current-devices.yaml").write_text("devices:\n  - name: router\n    address: 192.168.1.1\n")
    shown = body(ready.get("/", session))
    assert "<code>DEADMAN_URL</code>: set it in .env on the server." in shown
    (ready.helper / "env-set").write_text("UNIFI_API_KEY\nNTFY_TOPIC\nDEADMAN_URL\n")
    assert "Nothing's missing." in body(ready.get("/", session))


def test_home_says_when_it_cant_tell_and_what_an_on_switch_still_needs(ready: Dashboard) -> None:
    # yes is true to Helm, so ./ok3d check wants NTFY_TOPIC: Home mustn't say alerts go nowhere.
    settings_are(ready, SETTINGS + "alerts:\n  ntfy:\n    enabled: yes\nmodules:\n  unifi: true\n")
    session = ready.sign_in()
    shown = body(ready.get("/", session))
    assert "Setup can't tell whether ntfy is on" in shown
    assert "Alerts go nowhere yet" not in shown
    assert "UniFi is on, and needs your UniFi controller&#x27;s address, unifi.url" in shown
    assert "<code>alerts.ntfy.enabled: yes</code>" in body(ready.get("/setup", session))


def test_whats_next_comes_once_an_apply_has_worked(ready: Dashboard) -> None:
    settings_are(ready, SETTINGS + "tls:\n  domain: noc.example.org\ncluster:\n  ports:\n    https: 443\n")
    session = ready.sign_in()
    assert "What's next" not in body(ready.get("/", session))
    (ready.helper / "applied").write_text("2026-10-28T23:38:18Z\n")
    shown = body(ready.get("/", session))
    assert "What's next" in shown
    assert '<a href="https://grafana.noc.example.org/">' in shown
    assert "<code>*.noc.example.org</code>" in shown


def test_whats_next_never_links_to_a_domain_it_cant_trust(ready: Dashboard) -> None:
    settings_are(ready, SETTINGS + "tls:\n  domain: 'evil.example/\"><script>'\n")
    (ready.helper / "applied").write_text("2026-10-28T23:38:18Z\n")
    shown = body(ready.get("/", ready.sign_in()))
    assert "<script>" not in shown
    assert '<a href="https://grafana.noc.home.arpa:8443/">' in shown


# Releases and upgrades: ./ok3d upgrade writes newest-release and upgrade to the helper's
# folder; the Dashboard shows them, and sends only the release it found.

NEWER = "v99.0.0"


def found(dash: Dashboard, release: str = NEWER) -> None:
    (dash.helper / "newest-release").write_text(f"checked=2026-10-30T09:00:00Z\nnewest={release}\n")


def test_home_offers_to_look_for_a_release(ready: Dashboard) -> None:
    session = ready.sign_in()
    page = body(ready.get("/", session))
    assert "ok3d hasn't looked for a newer release yet." in page
    assert ready.post("/look-for-release", session=session).status == 303
    assert head(outbox(ready))["action"] == "look-for-release"


def test_home_shows_a_newer_release_with_its_notes_and_command(ready: Dashboard) -> None:
    found(ready)
    page = body(ready.get("/", ready.sign_in()))
    assert f"ok3d {NEWER} is out." in page
    assert f'href="https://github.com/southsidedean/observability-k3d/releases/tag/{NEWER}"' in page
    assert f"<code>./ok3d upgrade {NEWER}</code>" in page
    assert '<form method="get" action="/upgrade">' in page


def test_a_release_that_isnt_newer_isnt_offered(ready: Dashboard) -> None:
    found(ready, "v0.0.1")
    session = ready.sign_in()
    assert "No newer release when ok3d last looked, at 2026-10-30T09:00:00Z." in body(ready.get("/", session))
    assert "no newer release to upgrade to" in body(ready.get("/upgrade", session))
    assert ready.post("/upgrade", "version=v0.0.1", session=session).status == 409
    assert not (ready.state / "outbox" / "request").exists()


def test_the_upgrade_page_says_what_happens_then_sends_the_release(ready: Dashboard) -> None:
    found(ready)
    session = ready.sign_in()
    page = body(ready.get("/upgrade", session))
    assert f"Upgrade to ok3d {NEWER}" in page and "signed with ok3d's release key" in page
    assert ready.post("/upgrade", f"version={NEWER}", session=session).status == 303
    request = outbox(ready)
    fields = head(request)
    assert request == f"id={fields['id']}\naction=upgrade\nversion={NEWER}\n".encode()


@pytest.mark.parametrize("form", ["version=v98.0.0", "version=v99.0.0%0Aaction=apply", "", "version=main"])
def test_only_the_release_on_offer_is_sent(ready: Dashboard, form: str) -> None:
    found(ready)
    assert ready.post("/upgrade", form, session=ready.sign_in()).status == 409
    assert not (ready.state / "outbox" / "request").exists()


def test_a_newest_release_file_that_isnt_ok3ds_is_ignored(ready: Dashboard) -> None:
    (ready.helper / "newest-release").write_text("checked=2026-10-30T09:00:00Z\nnewest=v1.0.0<script>\n")
    session = ready.sign_in()
    assert "<script>" not in body(ready.get("/", session))
    assert ready.post("/upgrade", "version=v1.0.0", session=session).status == 409


def test_a_running_upgrade_shows_how_its_going_and_stops_everything_else(ready: Dashboard) -> None:
    (ready.helper / "upgrade").write_text("from=0.5.1\nto=v0.5.2\nstate=running\nstep=Deleting the cluster\n"
                                          "started=2026-10-30T09:00:00Z\n")
    (ready.helper / "upgrade-output").write_text("== Moving to v0.5.2\n<b>printed</b>\n")
    session = ready.sign_in()
    page = body(ready.get("/", session))
    assert "From ok3d 0.5.1 to v0.5.2, started at 2026-10-30T09:00:00Z. Now: Deleting the cluster." in page
    assert "&lt;b&gt;printed&lt;/b&gt;" in page
    assert 'action="/check"' not in page
    for path, form in (("/check", ""), ("/look-for-release", ""), ("/keys", "name=NTFY_TOPIC&value=x")):
        assert ready.post(path, form, session=session).status == 409, path
    assert not (ready.state / "outbox" / "request").exists()


@pytest.mark.parametrize(("state", "says"), [("finished", "finished at 2026-10-30T09:40:00Z."),
                                             ("failed", "stopped at 2026-10-30T09:40:00Z: ./ok3d apply failed")])
def test_home_says_how_the_last_upgrade_went(ready: Dashboard, state: str, says: str) -> None:
    (ready.helper / "upgrade").write_text(f"from=0.5.1\nto=v0.5.2\nstate={state}\nstep=./ok3d apply failed\n"
                                          "finished=2026-10-30T09:40:00Z\n")
    page = body(ready.get("/", ready.sign_in()))
    assert f"The upgrade from ok3d 0.5.1 to v0.5.2 {says}" in page
    assert 'action="/check"' in page


def test_only_the_end_of_a_long_upgrade_is_shown(tmp_path: Path) -> None:
    from ok3d.dashboard import helper_link

    (tmp_path / "upgrade").write_text("state=running\n")
    (tmp_path / "upgrade-output").write_text("".join(f"line {n}\n" for n in range(10_000)))
    shown = helper_link.upgrade(tmp_path)
    assert shown is not None
    assert shown.output.endswith("line 9999\n") and len(shown.output) <= helper_link.UPGRADE_TAIL
    assert shown.output.startswith("line ")  # from the start of a line


@pytest.mark.parametrize(("tag", "version", "newer"), [
    ("v0.5.1", "0.5.0", True), ("v0.5.1", "0.5.1.dev0", True), ("v0.5.1", "0.5.1", False),
    ("v0.5.0", "0.5.1.dev0", False), ("v0.10.0", "0.9.9", True), ("v1.0.0", "0.99.0", True),
    ("v0.5", "0.4.0", False), ("main", "0.4.0", False),
])  # fmt: skip
def test_which_releases_are_newer(tag: str, version: str, newer: bool) -> None:
    from ok3d.dashboard import helper_link

    assert helper_link.is_newer(tag, version) is newer



# Apply asks first: ./ok3d check writes apply-plan, what Apply would change in the running
# cluster, and Apply asks before it restarts or stops anything.


def checked(dash: Dashboard, session: str, plan: str | None) -> None:
    """A Check this Dashboard sent, which passed, and the plan it wrote (none: no file)."""
    dash.post("/check", session=session)
    sent = head(outbox(dash))["id"]
    (dash.state / "outbox" / "request").unlink()
    (dash.helper / "result").write_text(f"id={sent}\naction=check\nstate=finished\nexit=0\n\nReady.\n")
    if plan is not None:
        (dash.helper / "apply-plan").write_text("checked=2026-10-30T09:00:00Z\n" + plan)


@pytest.mark.parametrize("plan", ["state=new\n", "state=none\nother=0\n", "state=changes\nstart=Grafana\nother=4\n"])
def test_apply_goes_ahead_when_it_stops_nothing(ready: Dashboard, plan: str) -> None:
    session = ready.sign_in()
    checked(ready, session, plan)
    assert ready.post("/apply", session=session).status == 303
    assert head(outbox(ready))["action"] == "apply"


@pytest.mark.parametrize("plan", ["state=changes\nrestart=Grafana\nother=0\n",
                                  "state=changes\nstop=the UniFi exporter (unpoller)\nother=0\n",
                                  "state=unknown\n", None])  # fmt: skip
def test_apply_asks_first_when_it_would_restart_or_stop_something(ready: Dashboard, plan: str | None) -> None:
    session = ready.sign_in()
    checked(ready, session, plan)
    page = body(ready.post("/apply", session=session))
    assert "<h2>Apply?</h2>" in page and 'name="confirm" value="yes"' in page
    assert not (ready.state / "outbox" / "request").exists()
    assert ready.post("/apply", "confirm=yes", session=session).status == 303
    assert head(outbox(ready))["action"] == "apply"


def test_home_and_the_question_name_what_apply_would_change(ready: Dashboard) -> None:
    session = ready.sign_in()
    checked(ready, session, "state=changes\nrestart=Grafana\nstop=the UniFi exporter (unpoller)\n"
                            "start=Prometheus\nother=3\n")  # fmt: skip
    home_page = body(ready.get("/", session))
    for line in ("Restart Grafana", "Stop the UniFi exporter (unpoller)", "Start Prometheus", "3 other change(s)"):
        assert line in home_page, line
    assert "Restart Grafana" in body(ready.post("/apply", session=session))


def test_no_plan_is_shown_before_a_check_has_passed(ready: Dashboard) -> None:
    (ready.helper / "apply-plan").write_text("checked=2026-10-30T09:00:00Z\nstate=changes\nrestart=Grafana\n")
    assert "Restart Grafana" not in body(ready.get("/", ready.sign_in()))  # no Check passed yet


def test_a_plan_line_that_isnt_a_parts_name_is_left_out(ready: Dashboard) -> None:
    session = ready.sign_in()
    checked(ready, session, "state=changes\nrestart=<script>alert(1)</script>\nrestart=Grafana\n")
    page = body(ready.get("/", session))
    assert "<script>" not in page and "alert(1)" not in page
    assert "Restart Grafana" in page



def test_a_restart_whose_name_cant_be_shown_still_asks(ready: Dashboard) -> None:
    session = ready.sign_in()
    checked(ready, session, f"state=changes\nrestart=Deployment/{'x' * 120}\nother=0\n")
    page = body(ready.post("/apply", session=session))
    assert "<h2>Apply?</h2>" in page and "1 more part(s), whose names can't be shown here" in page
    assert not (ready.state / "outbox" / "request").exists()


# Each choice on the Dashboard is shown as what you'd do on the server instead.

def test_each_page_shows_its_server_command(ready: Dashboard) -> None:
    (ready.helper / "current-settings.yaml").write_text("modules:\n  unifi: false\n")
    session = ready.sign_in()
    shown = {
        "/": "On the server: <code>./ok3d check</code>, then <code>./ok3d apply</code>.",
        "/settings": "On the server: edit <code>settings.yaml</code> in the ok3d folder, then <code>./ok3d check</code>.",
        "/devices": "On the server: edit <code>devices.yaml</code> in the ok3d folder, then <code>./ok3d check</code>.",
        "/keys": "On the server: the line <code>NTFY_TOPIC=</code> in <code>.env</code>.",
        "/setup": "In settings.yaml: <code>modules.unifi: true</code>",
        "/setup ": "a dot means one setting inside another",
    }
    for path, line in shown.items():
        assert line in body(ready.get(path.strip(), session)), path


def test_each_ready_made_setup_shows_the_settings_it_writes() -> None:
    from ok3d.dashboard import server, switches

    card = next(c for c in switches.CARDS if c.available)
    html_text = server.card_html(card, "modules:\n  unifi: false\n", "none")
    for setting, on in card.changes().items():
        assert f"<code>{setting}: {'true' if on else 'false'}</code>" in html_text
