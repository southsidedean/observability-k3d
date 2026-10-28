"""The simulated network: the fake UniFi controller's metrics, the devices' web page, the two
lists of devices staying in step, and `ok3d demo` itself with a stand-in for docker.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import threading
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from ok3d import demo_device, demo_exporter

ROOT = Path(__file__).resolve().parent.parent
NETWORK = ROOT / "demo" / "network.tsv"
DASHBOARDS = ROOT / "manifests" / "monitoring" / "dashboards" / "unifi"

# A sample line in Prometheus's text format: a name, labels, and a number.
SAMPLE = re.compile(r'^([a-z_][a-z0-9_]*)(\{([a-z_]+="[^"\\]*"(,[a-z_]+="[^"\\]*")*)?\})? -?[0-9.e+-]+$')


def samples(text: str) -> dict[str, list[tuple[str, float]]]:
    """Every sample, by metric name, as (labels, value). Fails on a line that isn't valid."""
    found: dict[str, list[tuple[str, float]]] = {}
    for line in text.splitlines():
        if line.startswith("#"):
            assert re.match(r"^# (HELP|TYPE) [a-z_]+ ", line), line
            continue
        match = SAMPLE.match(line)
        assert match, f"not a valid sample: {line!r}"
        found.setdefault(match.group(1), []).append((match.group(2) or "", float(line.rsplit(" ", 1)[1])))
    return found


@pytest.fixture
def devices() -> list[demo_exporter.Device]:
    return demo_exporter.load_network(NETWORK)


def test_the_network_holds_the_demo_devices(devices: list[demo_exporter.Device]) -> None:
    names = [d.name for d in devices]
    assert "router" in names and "unifi-controller" in names
    assert len(names) == len(set(names)), "a device name is listed twice"
    addresses = [d.address for d in devices]
    assert len(addresses) == len(set(addresses)), "an address is used twice"
    # The documentation range, below .192: Docker hands out .192 to .223 itself (to the
    # cluster's node, say), and .254 is its gateway. A device in that range could have its
    # address taken while it's failed.
    assert all(re.fullmatch(r"198\.51\.100\.([1-9]|[1-9][0-9]|1[0-8][0-9]|19[01])", a) for a in addresses)


def test_devices_demo_yaml_matches_the_network(devices: list[demo_exporter.Device]) -> None:
    text = (ROOT / "devices.demo.yaml").read_text()
    listed = dict(re.findall(r"- name: (\S+)\n\s+address: (\S+)", text))
    assert listed == {d.name: d.address for d in devices}


def test_every_metric_is_one_unpoller_has_and_the_dashboards_use(devices: list[demo_exporter.Device]) -> None:
    # The point of the fake: the real dashboards (and, from 0.4, the real alert rules) work on
    # it unchanged. A name the dashboards don't know would mean the fake drifted from unpoller.
    known = set()
    for dashboard in DASHBOARDS.glob("*.json"):
        known |= set(re.findall(r"unpoller_[a-z_]+", dashboard.read_text()))
    rendered = samples(demo_exporter.render(devices, set(), now=1000.0, started=0.0))
    assert rendered, "nothing was rendered"
    assert set(rendered) <= known, f"not unpoller metrics the dashboards use: {set(rendered) - known}"


def test_counters_rise_and_ratios_stay_in_range(devices: list[demo_exporter.Device]) -> None:
    early = samples(demo_exporter.render(devices, set(), now=100.0, started=0.0))
    later = samples(demo_exporter.render(devices, set(), now=200.0, started=0.0))
    for name in early:
        if name.endswith("_total"):
            for (labels, before), (_, after) in zip(early[name], later[name], strict=True):
                assert after > before, f"{name}{labels} didn't rise"
        if name.endswith("_ratio"):
            assert all(0 <= value <= 1 for _, value in early[name]), name


def test_only_unifi_devices_are_reported(devices: list[demo_exporter.Device]) -> None:
    info = samples(demo_exporter.render(devices, set(), now=100.0, started=0.0))["unpoller_device_info"]
    reported = {re.search(r'[{,]name="([^"]+)"', labels).group(1) for labels, _ in info}  # type: ignore[union-attr]
    assert reported == {d.name for d in devices if d.is_unifi}


def test_a_failed_device_drops_out(devices: list[demo_exporter.Device]) -> None:
    rendered = demo_exporter.render(devices, {"upstairs-ap"}, now=100.0, started=0.0)
    assert 'name="upstairs-ap"' not in rendered
    assert 'name="living-room-ap"' in rendered
    assert samples(rendered)["unpoller_site_aps"][0][1] == 1


def test_the_failed_list_is_read_from_the_state_folder(tmp_path: Path) -> None:
    assert demo_exporter.load_failed(tmp_path) == set()
    (tmp_path / "failed").write_text("router\n\nnas\n")
    assert demo_exporter.load_failed(tmp_path) == {"router", "nas"}


def test_macs_are_stable_and_never_a_real_vendors(devices: list[demo_exporter.Device]) -> None:
    for device in devices:
        assert device.mac == demo_exporter.load_network(NETWORK)[devices.index(device)].mac
        # 02 sets the "locally administered" bit: no manufacturer uses these.
        assert device.mac.startswith("02:")


@pytest.fixture
def running(tmp_path: Path) -> Iterator[str]:
    """The exporter, served on a free port on this machine for the length of a test."""
    server: ThreadingHTTPServer = demo_exporter.make_server(NETWORK, tmp_path, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_the_exporter_serves_metrics_and_nothing_else(running: str) -> None:
    with urllib.request.urlopen(f"{running}/metrics") as response:  # noqa: S310
        assert response.status == 200
        assert response.headers["Content-Type"].startswith("text/plain")
        assert "unpoller_device_info" in response.read().decode()
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(f"{running}/admin")  # noqa: S310
    assert refused.value.code == 404


def test_the_device_page_names_the_device_safely() -> None:
    assert b"<h1>nas</h1>" in demo_device.page("nas")
    assert b"<script>" not in demo_device.page("<script>")


# ok3d demo, with stand-ins: docker logs every call, and network and container lookups answer
# from FAKE_* variables. uname says Darwin, as in test_ok3d.py.
FAKE_DOCKER = r"""echo "docker $*" >>"$FAKE_LOG"
case "$1 $2" in
"network inspect") exit "${FAKE_NETWORK:-1}" ;;
"container inspect") exit "${FAKE_CONTAINER:-1}" ;;
"ps --all") echo "${FAKE_PS:-}" ;;
esac"""
FAKE_HELM = r"""case "$*" in
*cluster-settings.yaml*)
	printf '%s\n' '  CLUSTER_NAME: "ok3d"' '  K3S_IMAGE: "rancher/k3s:v1.37.1-k3s1"' '  NETWORK: "ok3d"' \
		'  API_PORT: "6445"' '  PUBLISH_ADDRESS: "0.0.0.0"' '  HTTPS_PORT: "8443"' \
		"  DATA_ROOT: \"$FAKE_DATA_ROOT\"" '  TLS_MODE: "self-issued"' '  DOMAIN: "noc.home.arpa"' ;;
esac"""


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {"docker": FAKE_DOCKER, "helm": FAKE_HELM, "uname": "echo Darwin"}.items():
        path = bin_dir / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "data").mkdir()
    (tmp_path / "settings.yaml").write_text("settingsVersion: 1\n")
    return {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_LOG": str(tmp_path / "calls.log"),
        "FAKE_DATA_ROOT": str(tmp_path / "data"),
        "OK3D_SETTINGS": str(tmp_path / "settings.yaml"),
    }


def demo(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(ROOT / "ok3d"), "demo", *args], capture_output=True, text=True, env=env, check=False)


def calls(env: dict[str, str]) -> list[str]:
    log = Path(env["FAKE_LOG"])
    return log.read_text().splitlines() if log.exists() else []


def test_demo_up_makes_the_network_and_starts_every_device_locked_down(
    env: dict[str, str], devices: list[demo_exporter.Device]
) -> None:
    result = demo(env, "up")
    assert result.returncode == 0, result.stderr
    log = calls(env)
    assert any("network create --subnet 198.51.100.0/24 --gateway 198.51.100.254 --ip-range 198.51.100.192/27" in line for line in log)
    runs = [line for line in log if line.startswith("docker run")]
    assert len(runs) == len(devices)
    for device, run in zip(devices, runs, strict=True):
        assert f"--name ok3d-demo-{device.name} " in run
        assert f"--ip {device.address} " in run
        for flag in ("--read-only", "--cap-drop ALL", "--security-opt no-new-privileges", "--user 65534:65534"):
            assert flag in run, f"{device.name} runs without {flag}"
        assert "@sha256:" in run, "the image isn't pinned by digest"
    controller = next(run for run in runs if "ok3d-demo-unifi-controller" in run)
    assert "demo_exporter.py" in controller
    nas = next(run for run in runs if "ok3d-demo-nas " in run)
    assert "demo_device.py --name nas --port 80" in nas
    assert (Path(env["FAKE_DATA_ROOT"]) / "demo" / "failed").read_text() == ""


def test_demo_fail_and_fix_stop_and_start_a_device_and_tell_the_controller(env: dict[str, str]) -> None:
    failed = Path(env["FAKE_DATA_ROOT"]) / "demo" / "failed"
    assert demo(env, "fail", "upstairs-ap").returncode == 0
    assert "docker stop ok3d-demo-upstairs-ap" in calls(env)
    assert failed.read_text().split() == ["upstairs-ap"]
    assert demo(env, "fail", "upstairs-ap").returncode == 0  # twice is still one entry
    assert failed.read_text().split() == ["upstairs-ap"]
    assert demo(env, "fix", "upstairs-ap").returncode == 0
    assert "docker start ok3d-demo-upstairs-ap" in calls(env)
    assert failed.read_text().split() == []


def test_demo_fail_refuses_a_device_that_isnt_in_the_demo(env: dict[str, str]) -> None:
    result = demo(env, "fail", "toaster")
    assert result.returncode == 2
    assert "router" in result.stderr
    assert not any(line.startswith("docker stop") for line in calls(env))


def test_demo_down_removes_the_containers_the_network_and_the_state(env: dict[str, str]) -> None:
    state = Path(env["FAKE_DATA_ROOT"]) / "demo"
    state.mkdir()
    (state / "failed").write_text("nas\n")
    env["FAKE_PS"] = "abc123 def456"
    env["FAKE_NETWORK"] = "0"
    result = demo(env, "down")
    assert result.returncode == 0, result.stderr
    log = calls(env)
    assert "docker rm --force abc123 def456" in log
    assert "docker network rm ok3d-demo" in log
    assert not state.exists()
