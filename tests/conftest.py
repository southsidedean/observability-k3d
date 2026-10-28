"""Shared test setup: a fence that keeps every test off the network.

No test may reach the internet or the local network. A test that tries fails at once with a
clear message, instead of passing on one machine and failing on another, or quietly talking
to a real device. Connections to this machine itself (a test server on 127.0.0.1, say) are
allowed.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterator
from typing import Any

import pytest

_real_connect = socket.socket.connect


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


def _fenced_connect(self: socket.socket, address: Any) -> None:
    if not _is_local(address):
        raise RuntimeError(f"tests may not reach the network (tried {address!r})")
    _real_connect(self, address)


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Applied to every test: only connections to this machine are allowed."""
    monkeypatch.setattr(socket.socket, "connect", _fenced_connect)
    yield
