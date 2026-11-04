"""Shared test setup: a fence that keeps every test off the network.

No test may reach the internet or the local network. A Python socket in the test process
that tries to connect or send anywhere else fails at once with a clear message, so no test
depends on the machine it runs on or talks to a real device. Connections to this machine
itself (a test server on 127.0.0.1, say) are allowed.

It can't fence the programs tests run (./ok3d, git, sh install.sh) the same way: those reach
only the stand-ins and the local repositories each test sets up. Every subprocess also gets
a proxy that leads nowhere and git limited to local repositories, so most that tried would
fail too, though a program that ignores proxies (or looks up a name) wouldn't be stopped.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Iterator
from typing import Any

import pytest

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_sendto = socket.socket.sendto


def _is_local(address: Any) -> bool:
    """Whether a socket address points at this machine (or is a Unix socket path)."""
    if isinstance(address, (str, bytes)):
        return True  # a Unix socket: a file on this machine
    host = address[0]
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False  # a host name other than localhost would need DNS: off limits


def _refuse(address: Any) -> None:
    if not _is_local(address):
        raise RuntimeError(f"tests may not reach the network (tried {address!r})")


def _fenced_connect(self: socket.socket, address: Any) -> None:
    _refuse(address)
    _real_connect(self, address)


def _fenced_connect_ex(self: socket.socket, address: Any) -> int:
    _refuse(address)
    return _real_connect_ex(self, address)


def _fenced_sendto(self: socket.socket, data: Any, *args: Any) -> int:
    _refuse(args[-1])  # sendto(data, address) or sendto(data, flags, address)
    return int(_real_sendto(self, data, *args))


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Applied to every test: only connections to this machine are allowed, from here and
    from the programs a test runs."""
    monkeypatch.setattr(socket.socket, "connect", _fenced_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _fenced_connect_ex)
    monkeypatch.setattr(socket.socket, "sendto", _fenced_sendto)
    # Inherited by every subprocess: web requests go to a port nothing listens on, and git
    # may use only local repositories.
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    for name in ("no_proxy", "NO_PROXY"):
        monkeypatch.setenv(name, "localhost,127.0.0.1,::1")  # the tests' own servers
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    yield


# Set by git for its hooks, so a test run by the pre-push hook would otherwise inherit them:
# then every git the tests run (git init, commit, tag, config in a test's own folder) acts on
# this repository instead. From a worktree that happened: test commits on the branch being
# pushed, and the repository's config changed. The tests make their own repositories, so
# none of these may reach them.
_GIT_LOCATION = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
                 "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_PREFIX", "GIT_QUARANTINE_PATH")


def pytest_configure(config: pytest.Config) -> None:
    """Before any test or fixture: forget which repository git was called in."""
    for name in _GIT_LOCATION:
        os.environ.pop(name, None)
