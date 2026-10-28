"""The ok3d command, run for real with stand-ins for docker, k3d, helm, kubectl, openssl, and
uname: what it checks, what it makes, in what order, and what it refuses. The stand-ins write
each call to a log, so a test can see exactly what ok3d would have run. (The real thing is
tested on the test VM: PLAN.md, "The test VM".)
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Each stand-in logs its name and arguments, then does just enough to keep ok3d going. Their
# behavior can be changed per test through FAKE_* variables.
FAKES = {
    "docker": 'echo "docker $*" >>"$FAKE_LOG"; exit "${FAKE_DOCKER_STATUS:-0}"',
    "k3d": r"""echo "k3d $*" >>"$FAKE_LOG"
case "$1 ${2:-}" in
"version "*) echo "k3d version v${FAKE_K3D_VERSION:-5.9.0}" ;;
"cluster get") exit "${FAKE_CLUSTER_GET:-1}" ;;
esac""",
    "helm": r"""echo "helm $*" >>"$FAKE_LOG"
case "$*" in
"version --short") echo "v4.3.1+g0" ;;
*cluster-settings.yaml*)
	cat <<EOF
---
apiVersion: v1
kind: ConfigMap
data:
  SETTINGS_VERSION: "1"
  CLUSTER_NAME: "ok3d"
  K3S_IMAGE: "rancher/k3s:v1.37.1-k3s1"
  NETWORK: "ok3d"
  API_PORT: "6445"
  PUBLISH_ADDRESS: "0.0.0.0"
  HTTPS_PORT: "8443"
  DATA_ROOT: "$FAKE_DATA_ROOT"
  TLS_MODE: "self-issued"
  DOMAIN: "${FAKE_DOMAIN:-noc.home.arpa}"
EOF
	;;
esac""",
    "kubectl": r"""echo "kubectl $*" >>"$FAKE_LOG"
case "$*" in *"--filename -"*) cat >/dev/null ;; *"--output yaml"*) echo "kind: Secret" ;; esac""",
    # Makes the key and certificate files, and answers the name-constraint question with
    # FAKE_CA_DOMAIN (the domain the existing authority was made for).
    "openssl": r"""echo "openssl $*" >>"$FAKE_LOG"
if [ "$1" = req ]; then
	while [ $# -gt 0 ]; do
		case "$1" in -keyout | -out) touch "$2"; shift ;; esac
		shift
	done
elif [ "$1" = x509 ]; then
	echo "    Permitted:"
	echo "      DNS:.${FAKE_CA_DOMAIN:-noc.home.arpa}"
fi""",
    # Darwin, so ok3d skips the Linux-only checks (inotify, free memory, the filesystem type)
    # whatever machine the tests run on.
    "uname": 'echo Darwin',
}


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """A PATH with the stand-ins first, a data root, and settings to point ok3d at."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in FAKES.items():
        path = bin_dir / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    data_root = tmp_path / "data"
    data_root.mkdir()
    settings = tmp_path / "settings.yaml"
    settings.write_text("settingsVersion: 1\n")
    return {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_LOG": str(tmp_path / "calls.log"),
        "FAKE_DATA_ROOT": str(data_root),
        "OK3D_SETTINGS": str(settings),
    }


def ok3d(env: dict[str, str], *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ROOT / "ok3d"), *args], capture_output=True, text=True, env=env, input=stdin, check=False
    )


def calls(env: dict[str, str]) -> list[str]:
    log = Path(env["FAKE_LOG"])
    return log.read_text().splitlines() if log.exists() else []


def test_without_settings_it_says_what_to_do(env: dict[str, str], tmp_path: Path) -> None:
    env["OK3D_SETTINGS"] = str(tmp_path / "missing.yaml")
    result = ok3d(env, "check")
    assert result.returncode == 1
    assert "Copy settings.example.yaml to settings.yaml" in result.stderr


def test_check_passes_on_a_ready_machine(env: dict[str, str]) -> None:
    result = ok3d(env, "check")
    assert result.returncode == 0, result.stdout
    assert "Ready." in result.stdout
    assert "FAIL" not in result.stdout


def test_check_refuses_an_old_k3d(env: dict[str, str]) -> None:
    env["FAKE_K3D_VERSION"] = "5.8.3"
    result = ok3d(env, "check")
    assert result.returncode == 1
    assert "k3d 5.8.3: ok3d needs 5.9.0 or newer" in result.stdout


def test_check_says_how_to_make_a_missing_data_root(env: dict[str, str], tmp_path: Path) -> None:
    env["FAKE_DATA_ROOT"] = str(tmp_path / "nowhere")
    result = ok3d(env, "check")
    assert result.returncode == 1
    assert "sudo install -d" in result.stdout


def test_check_says_when_docker_isnt_running(env: dict[str, str]) -> None:
    env["FAKE_DOCKER_STATUS"] = "1"
    result = ok3d(env, "check")
    assert result.returncode == 1
    assert "Docker isn't running" in result.stdout


def test_apply_makes_everything_in_order(env: dict[str, str]) -> None:
    result = ok3d(env, "apply")
    assert result.returncode == 0, result.stdout + result.stderr
    log = calls(env)

    def first(prefix: str) -> int:
        return next(i for i, line in enumerate(log) if line.startswith(prefix))

    # The authority, then the cluster, then the platform, the authority's Secret, and ok3d.
    assert first("openssl req") < first("k3d cluster create") < first("helm upgrade --install ok3d-platform")
    assert first("helm upgrade --install ok3d-platform") < first("kubectl --context k3d-ok3d --namespace cert-manager create secret tls ok3d-ca")
    assert first("kubectl --context k3d-ok3d --namespace cert-manager create secret") < first("helm upgrade --install ok3d chart/ok3d")

    create = log[first("k3d cluster create")]
    data_root = env["FAKE_DATA_ROOT"]
    assert "--servers 1 --agents 0" in create
    assert "--api-port 127.0.0.1:6445" in create  # the API never on the network
    assert f"--volume {data_root}:/var/lib/ok3d@server:0" in create
    assert f"--volume {data_root}/kagent-ate:/var/lib/ate@server:0" in create
    assert "--kubeconfig-switch-context=false" in create  # your current context stays

    # The authority's name constraint keeps it to the domain.
    req = log[first("openssl req")]
    assert "nameConstraints=critical,permitted;DNS:noc.home.arpa,permitted;DNS:.noc.home.arpa" in req

    certs = Path(data_root) / "certs"
    assert stat.S_IMODE(certs.stat().st_mode) == 0o700
    assert (Path(data_root) / "kagent-ate").is_dir()


def test_apply_keeps_an_existing_cluster_and_authority(env: dict[str, str]) -> None:
    certs = Path(env["FAKE_DATA_ROOT"]) / "certs"
    certs.mkdir(mode=0o700)
    (certs / "ca.crt").write_text("cert")
    (certs / "ca.key").write_text("key")
    env["FAKE_CLUSTER_GET"] = "0"
    result = ok3d(env, "apply")
    assert result.returncode == 0, result.stdout + result.stderr
    log = calls(env)
    assert not any(line.startswith("k3d cluster create") for line in log)
    assert not any(line.startswith("openssl req") for line in log)
    assert "is kept" in result.stdout


def test_apply_refuses_an_authority_made_for_another_domain(env: dict[str, str]) -> None:
    certs = Path(env["FAKE_DATA_ROOT"]) / "certs"
    certs.mkdir(mode=0o700)
    (certs / "ca.crt").write_text("cert")
    (certs / "ca.key").write_text("key")
    env["FAKE_CA_DOMAIN"] = "noc.example.org"
    result = ok3d(env, "apply")
    assert result.returncode == 1
    assert "is for another domain" in result.stderr
    assert not any(line.startswith("k3d cluster create") for line in calls(env))


def test_delete_needs_a_yes(env: dict[str, str]) -> None:
    result = ok3d(env, "delete")
    assert result.returncode == 1
    assert "--yes" in result.stderr
    assert not any(line.startswith("k3d cluster delete") for line in calls(env))


def test_delete_with_yes_deletes_the_cluster_and_keeps_the_data(env: dict[str, str]) -> None:
    keep = Path(env["FAKE_DATA_ROOT"]) / "grafana"
    keep.mkdir()
    result = ok3d(env, "delete", "--yes")
    assert result.returncode == 0
    assert "k3d cluster delete ok3d" in calls(env)
    assert keep.is_dir()


def test_an_unknown_command_shows_the_usage(env: dict[str, str]) -> None:
    result = ok3d(env, "nosuch")
    assert result.returncode == 2
    assert "./ok3d apply" in result.stderr


def test_version_matches_the_package() -> None:
    from ok3d import __version__

    result = subprocess.run([str(ROOT / "ok3d"), "version"], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == f"ok3d {__version__}"
