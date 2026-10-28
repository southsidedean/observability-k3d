"""Starts the Dashboard: python -m ok3d.dashboard (the image's entry point)."""

from __future__ import annotations

import argparse
from pathlib import Path

from ok3d.dashboard.server import Config, make_server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ok3d-dashboard", description="Serves the ok3d Dashboard over HTTPS.")
    parser.add_argument("--state", type=Path, default=Path("/state"), help="<data root>/dashboard")
    parser.add_argument("--helper", type=Path, default=Path("/helper"), help="<data root>/helper, read-only")
    parser.add_argument("--cert", type=Path, default=Path("/state/tls/dashboard.crt"))
    parser.add_argument("--key", type=Path, default=Path("/state/tls/dashboard.key"))
    # Every address inside its container; the installer publishes the port on the server.
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104  # nosec B104
    parser.add_argument("--port", type=int, default=8444)
    args = parser.parse_args(argv)
    if not args.cert.is_file() or not args.key.is_file():
        raise SystemExit(f"ok3d-dashboard: no certificate at {args.cert} and {args.key}; it serves HTTPS only")
    server = make_server(Config(args.state, args.helper), args.host, args.port, args.cert, args.key)
    print(f"ok3d-dashboard: serving on port {args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
