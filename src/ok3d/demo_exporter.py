"""A fake UniFi controller for the simulated network: it serves the metrics unpoller would.

`./ok3d demo up` runs this in the demo's unifi-controller container. It reads the demo's
devices from network.tsv and reports on the UniFi ones the way unpoller does, under the same
metric names (unpoller_*) and labels the vendored UniFi dashboards query. Values move over
time: counters keep rising and load drifts, so graphs and rate() have something to show.

A device named in the state folder's `failed` file (written by `./ok3d demo fail <name>`)
drops out of the report, as a device the controller can't reach does.

It uses only the standard library, so it runs in a stock Python image with no install step.
Run it by hand with:
    python3 demo_exporter.py --network demo/network.tsv --state /tmp/state --port 9130
"""

from __future__ import annotations

import argparse
import hashlib
import math
import time
from collections.abc import Iterable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SITE = "Home"
SOURCE = "ok3d-demo"
# The ports each simulated switch reports, and the clients each access point has at most.
SWITCH_PORTS = 8
CLIENTS_PER_AP = 12


@dataclass(frozen=True)
class Device:
    """One line of network.tsv."""

    name: str
    address: str
    role: str
    unifi_type: str  # ugw, usw, uap, or "-" for a device that isn't UniFi
    model: str
    http: bool

    @property
    def is_unifi(self) -> bool:
        return self.unifi_type != "-"

    @property
    def mac(self) -> str:
        """A made-up MAC address, the same every time for the same name, in the locally
        administered range (02:...) so it can't be a real device's."""
        digest = hashlib.sha256(self.name.encode()).digest()
        return "02:" + ":".join(f"{b:02x}" for b in digest[:5])

    @property
    def seed(self) -> float:
        """A number from 0 to 1, fixed per device, so each one's graphs differ from the rest."""
        return hashlib.sha256(self.name.encode()).digest()[0] / 255


def load_network(path: Path) -> list[Device]:
    """The devices in network.tsv. Blank lines and lines starting with # are skipped."""
    devices = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if not fields or fields[0].startswith("#"):
            continue
        name, address, role, unifi_type, model, http = fields
        devices.append(Device(name, address, role, unifi_type, model, http == "http"))
    return devices


def load_failed(state: Path) -> set[str]:
    """The devices `ok3d demo fail` has taken down, one name per line in state/failed."""
    try:
        return {line.strip() for line in (state / "failed").read_text().splitlines() if line.strip()}
    except FileNotFoundError:
        return set()


def _labels(**labels: str | int) -> str:
    return "{" + ",".join(f'{key}="{value}"' for key, value in labels.items()) + "}"


def _wave(device: Device, now: float, period: float) -> float:
    """A slow wave from -1 to 1, offset per device."""
    return math.sin(now / period + device.seed * 2 * math.pi)


def render(devices: Iterable[Device], failed: set[str], now: float, started: float) -> str:
    """The metrics, in Prometheus's text format, as unpoller would report them at `now`."""
    up = [d for d in devices if d.is_unifi and d.name not in failed]
    elapsed = max(now - started, 0.0)
    lines: list[str] = []

    def metric(name: str, kind: str, about: str, samples: list[tuple[str, float]]) -> None:
        lines.append(f"# HELP {name} {about}")
        lines.append(f"# TYPE {name} {kind}")
        lines.extend(f"{name}{labels} {value:.6g}" for labels, value in samples)

    def device_labels(d: Device) -> str:
        return _labels(
            site_name=SITE, source=SOURCE, name=d.name, mac=d.mac, model=d.model, type=d.unifi_type,
            ip=d.address, version="4.0.0", serial=d.mac.replace(":", "").upper(),
        )

    aps = [d for d in up if d.unifi_type == "uap"]
    stations = {d.name: round((CLIENTS_PER_AP / 2) * (1 + 0.6 * _wave(d, now, 1800))) for d in aps}

    metric("unpoller_device_info", "gauge", "Device information.", [(device_labels(d), 1) for d in up])
    metric("unpoller_device_uptime_seconds", "gauge", "Device uptime.",
           [(device_labels(d), 3600 * 24 * 7 * (1 + d.seed) + elapsed) for d in up])
    metric("unpoller_device_cpu_utilization_ratio", "gauge", "Device CPU use, from 0 to 1.",
           [(device_labels(d), 0.15 + 0.1 * _wave(d, now, 300)) for d in up])
    metric("unpoller_device_memory_utilization_ratio", "gauge", "Device memory use, from 0 to 1.",
           [(device_labels(d), 0.45 + 0.05 * _wave(d, now, 900)) for d in up])
    metric("unpoller_device_stations", "gauge", "Clients on each access point.",
           [(device_labels(d), stations[d.name]) for d in aps])

    ports: list[tuple[str, float]] = []
    ports_out: list[tuple[str, float]] = []
    for d in (d for d in up if d.unifi_type == "usw"):
        for port in range(1, SWITCH_PORTS + 1):
            labels = _labels(site_name=SITE, source=SOURCE, name=d.name, port_num=port, port_name=f"Port {port}")
            rate = 20_000 * port * (1 + d.seed)  # bytes a second: each port busier than the last
            ports.append((labels, rate * elapsed))
            ports_out.append((labels, rate * 0.4 * elapsed))
    metric("unpoller_device_port_receive_bytes_total", "counter", "Bytes each switch port received.", ports)
    metric("unpoller_device_port_transmit_bytes_total", "counter", "Bytes each switch port sent.", ports_out)

    gateways = [d for d in up if d.unifi_type == "ugw"]
    metric("unpoller_device_wan_receive_bytes_total", "counter", "Bytes the gateway received from the internet.",
           [(device_labels(d), 2_500_000 * elapsed) for d in gateways])
    metric("unpoller_device_wan_transmit_bytes_total", "counter", "Bytes the gateway sent to the internet.",
           [(device_labels(d), 400_000 * elapsed) for d in gateways])

    site = _labels(site_name=SITE, source=SOURCE)
    metric("unpoller_site_stations", "gauge", "Clients at the site.", [(site, sum(stations.values()) + 4)])
    metric("unpoller_site_aps", "gauge", "Access points at the site.", [(site, len(aps))])
    metric("unpoller_site_switches", "gauge", "Switches at the site.",
           [(site, sum(1 for d in up if d.unifi_type == "usw"))])
    metric("unpoller_site_gateways", "gauge", "Gateways at the site.", [(site, len(gateways))])
    metric("unpoller_site_latency_seconds", "gauge", "The internet link's latency.",
           [(site, 0.015 + 0.005 * math.sin(now / 600))])

    clients = [
        (_labels(site_name=SITE, source=SOURCE, name=f"{ap.name}-client-{n}", ap_name=ap.name, radio_desc="5 GHz"),
         600 * n + elapsed)
        for ap in aps
        for n in range(1, stations[ap.name] + 1)
    ]
    metric("unpoller_client_uptime_seconds", "gauge", "How long each client has been connected.", clients)
    return "\n".join(lines) + "\n"


def make_server(network: Path, state: Path, host: str, port: int) -> ThreadingHTTPServer:
    """A server for /metrics, not yet serving. Reads network.tsv and the failed list on every
    scrape, so `ok3d demo fail` shows up at the next one."""
    started = time.time()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/metrics":
                self.send_error(404)
                return
            body = render(load_network(network), load_failed(state), time.time(), started).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass  # one line per scrape, every 30 seconds, would only bury real messages

    return ThreadingHTTPServer((host, port), Handler)


def serve(network: Path, state: Path, port: int) -> None:
    """Serves /metrics on every address until stopped: inside the controller's own container,
    on the demo's network, that's how Prometheus reaches it."""
    make_server(network, state, "0.0.0.0", port).serve_forever()  # nosec B104  # noqa: S104


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--network", type=Path, required=True, help="the demo's network.tsv")
    parser.add_argument("--state", type=Path, required=True, help="the folder ok3d demo fail writes to")
    parser.add_argument("--port", type=int, default=9130, help="the port to serve /metrics on")
    args = parser.parse_args()
    serve(args.network, args.state, args.port)


if __name__ == "__main__":
    main()
