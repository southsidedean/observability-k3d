"""The network fence in conftest.py: it blocks the outside and lets this machine through."""

from __future__ import annotations

import socket

import pytest


def test_a_connection_to_the_network_is_refused() -> None:
    # 192.0.2.1 is a documentation address (RFC 5737): nothing answers there anyway.
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s,
        pytest.raises(RuntimeError, match="may not reach the network"),
    ):
        s.connect(("192.0.2.1", 80))


def test_a_connection_to_this_machine_is_allowed() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.connect(server.getsockname())
