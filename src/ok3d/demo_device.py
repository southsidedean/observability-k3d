"""A simulated device's web page, for the demo devices that answer HTTP.

`./ok3d demo up` runs this in each demo container marked http in network.tsv, so ok3d's HTTP
checks have something to reach. It answers every GET with a short page naming the device.
Every demo device answers ping on its own, since that's the container's network stack.

It uses only the standard library, so it runs in a stock Python image with no install step.
"""

from __future__ import annotations

import argparse
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def page(name: str) -> bytes:
    """The page the device serves."""
    name = html.escape(name)
    return (
        f"<!doctype html><title>{name}</title>"
        f"<h1>{name}</h1><p>A simulated device on the ok3d demo network.</p>\n"
    ).encode()


def serve(name: str, port: int) -> None:
    body = page(name)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass  # a line for every probe would only bury real messages

    # Every address, inside its own container on the demo's network.
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()  # nosec B104  # noqa: S104


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", required=True, help="the device's name, shown on its page")
    parser.add_argument("--port", type=int, default=80)
    args = parser.parse_args()
    serve(args.name, args.port)


if __name__ == "__main__":
    main()
