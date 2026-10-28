"""Tests for the Dashboard's web server and sign-in (src/ok3d/dashboard/).

Each test starts the real server, over HTTPS with a throwaway certificate, and talks to it the
way a browser would: pages need a session, the password makes one, forms from other sites
are refused, wrong guesses are limited, and nothing from the helper's answer reaches the page
unescaped.
"""

from __future__ import annotations

import concurrent.futures
import http.client
import json
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
    assert f"Version {__version__}" in body(home)


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
    assert "No answer from the helper yet" in body(dash.get("/", dash.sign_in()))


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
