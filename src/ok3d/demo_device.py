"""A simulated device's web page, for the demo devices that answer HTTP.

`./ok3d demo up` runs this in each demo container marked http in network.tsv, so ok3d's HTTP
checks have something to reach. It answers every GET with a short page naming the device.
It also takes POSTs, the way a webhook receiver does, and logs one line for each, so a test
can point alerts at a demo device and see them arrive (`docker logs ok3d-demo-nas`). Every
demo device answers ping on its own, since that's the container's network stack.

It uses only the standard library, so it runs in a stock Python image with no install step.
"""

from __future__ import annotations

import argparse
import html
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# The most of a POST's body that's read; the rest is left unread. An alert is a few kilobytes.
MAX_BODY = 1 << 20


def page(name: str) -> bytes:
    """The page the device serves."""
    name = html.escape(name)
    return (
        f"<!doctype html><title>{name}</title>"
        f"<h1>{name}</h1><p>A simulated device on the ok3d demo network.</p>\n"
    ).encode()


def received(path: str, body: bytes) -> str:
    """The log line for a POST: where it went and how big it was, never what it said."""
    return f"received a POST to {path!r}, {len(body)} bytes"


def make_server(name: str, host: str, port: int) -> ThreadingHTTPServer:
    """A server for the device's page and its webhook, not yet serving."""
    body = page(name)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            length = min(int(self.headers.get("Content-Length") or 0), MAX_BODY)
            print(received(self.path.split("?", 1)[0], self.rfile.read(length)), flush=True, file=sys.stdout)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass  # a line for every probe would only bury real messages

    return ThreadingHTTPServer((host, port), Handler)


def serve(name: str, port: int) -> None:
    """Serves on every address until stopped: inside the device's own container, on the
    demo's network, that's how the checks reach it."""
    make_server(name, "0.0.0.0", port).serve_forever()  # nosec B104  # noqa: S104


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", required=True, help="the device's name, shown on its page")
    parser.add_argument("--port", type=int, default=80)
    args = parser.parse_args()
    serve(args.name, args.port)


if __name__ == "__main__":
    main()
