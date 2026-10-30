"""The ok3d command, run for real with stand-ins for docker, k3d, helm, kubectl, openssl, and
uname: what it checks, what it makes, in what order, and what it refuses. The stand-ins write
each call to a log, so a test can see exactly what ok3d would have run. (The real thing is
tested on the test VM: PLAN.md, "The test VM".)
"""

from __future__ import annotations

import fcntl
import os
import pty
import re
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Each stand-in logs its name and arguments, then does just enough to keep ok3d going. Their
# behavior can be changed per test through FAKE_* variables.
FAKES = {
    # docker run, for the Dashboard, makes its password, as the real one does on first start.
    "docker": r"""echo "docker $*" >>"$FAKE_LOG"
if [ "$1" = run ] && [ -d "$FAKE_DATA_ROOT/dashboard" ]; then printf 'kxq7-m2pa-9fht-3bnd\n' >"$FAKE_DATA_ROOT/dashboard/password"; fi
if [ "$1" = pull ]; then exit "${FAKE_PULL_STATUS:-0}"; fi
exit "${FAKE_DOCKER_STATUS:-0}"
""",
    "k3d": r"""echo "k3d $*" >>"$FAKE_LOG"
case "$1 ${2:-}" in
"version "*) echo "k3d version v${FAKE_K3D_VERSION:-5.9.0}" ;;
"cluster get") exit "${FAKE_CLUSTER_GET:-1}" ;;
esac""",
    "helm": r"""echo "helm $*" >>"$FAKE_LOG"
case "$*" in
"version --short") echo "v4.3.1+g0" ;;
"dependency list"*) ;;
"status ok3d"*) exit "${FAKE_OLD_RELEASE:-1}" ;;
# The release as it's deployed, and what Apply would deploy: from FAKE_MANIFEST and
# FAKE_DRY_RUN. Without FAKE_MANIFEST there's no release.
"get manifest ok3d"*) [ -n "${FAKE_MANIFEST:-}" ] && cat "$FAKE_MANIFEST" ;;
*--dry-run=server*) cat "${FAKE_DRY_RUN:-/dev/null}" ;;
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
  DASHBOARD_PORT: "${FAKE_DASHBOARD_PORT:-8444}"
  DATA_ROOT: "$FAKE_DATA_ROOT"
  TLS_MODE: "self-issued"
  DOMAIN: "${FAKE_DOMAIN:-noc.home.arpa}"
  METRICS_RETENTION: "30d"
  METRICS_RETENTION_SIZE: "40GB"
  MODULE_UNIFI: "${FAKE_UNIFI:-false}"
  ALERTS_NTFY: "${FAKE_NTFY:-false}"
  ALERTS_NTFY_SERVER: "https://ntfy.sh"
  ALERTS_NTFY_TOKEN: "${FAKE_NTFY_TOKEN:-false}"
  ALERTS_EMAIL: "${FAKE_EMAIL:-false}"
  ALERTS_DEADMAN: "${FAKE_DEADMAN:-false}"
EOF
	;;
esac""",
    "kubectl": r"""echo "kubectl $*" >>"$FAKE_LOG"
case "$*" in
*"--filename -"*) cat >>"$FAKE_LOG.stdin" ;;
*"--from-file=api-key=/dev/stdin"*) echo "stdin: $(cat)" >>"$FAKE_LOG.stdin"; echo "kind: Secret" ;;
*"--from-env-file=/dev/stdin"*)
	# Each Secret's contents in a file of its own, by namespace and name.
	name=$(echo "$*" | sed -n 's/.*--namespace \([^ ]*\) create secret generic \([^ ]*\).*/\1.\2/p')
	cat >"$FAKE_LOG.$name"; echo "kind: Secret" ;;
*"--output yaml"*) echo "kind: Secret" ;;
esac""",
    # Makes the key and certificate files, and answers the name-constraint question with
    # FAKE_CA_DOMAIN (the domain the existing authority was made for).
    "openssl": r"""echo "openssl $*" >>"$FAKE_LOG"
if [ "$1" = req ]; then
	while [ $# -gt 0 ]; do
		case "$1" in -keyout | -out) touch "$2"; shift ;; esac
		shift
	done
elif [ "$1" = x509 ] && [ "$2" = -req ]; then
	# What the certificate would say, kept for the test to read.
	while [ $# -gt 0 ]; do
		case "$1" in -extfile) cp "$2" "$FAKE_LOG.ext"; shift ;; -out) touch "$2"; shift ;; esac
		shift
	done
elif [ "$1" = x509 ]; then
	echo "    Permitted:"
	echo "      DNS:.${FAKE_CA_DOMAIN:-noc.home.arpa}"
elif [ "$1" = rand ]; then
	printf 'made-up-admin-password'
elif [ "$1" = dgst ]; then
	echo "0123abcd *stdin"
fi""",
    # Darwin, so ok3d skips the Linux-only checks (inotify, free memory, the filesystem type)
    # whatever machine the tests run on.
    "uname": 'echo "${FAKE_UNAME:-Darwin}"',
    "systemctl": 'echo "systemctl $*" >>"$FAKE_LOG"',
    # As util-linux's flock -n FD (macOS has none): the same kernel lock, taken on the shell's
    # open file, so it's held until the shell ends.
    "flock": 'exec python3 -c "import fcntl, sys; fcntl.flock(int(sys.argv[1]), fcntl.LOCK_EX | fcntl.LOCK_NB)" "$2" 2>/dev/null',
    "loginctl": 'echo "loginctl $*" >>"$FAKE_LOG"; echo "${FAKE_LINGER:-yes}"',
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

    # The authority, then the cluster, then the platform, the authority's Secret, the
    # monitoring namespace (with its labels, before anything is installed into it), and ok3d.
    assert first("openssl req") < first("k3d cluster create") < first("helm upgrade --install ok3d-platform")
    assert first("helm upgrade --install ok3d-platform") < first("kubectl --context k3d-ok3d --namespace cert-manager create secret tls ok3d-ca")
    # Five applies come before ok3d's release: the authority's Secret, the namespaces, the
    # alerts Secret, and the admin Secret in monitoring and gateway. (A Secret's create and
    # apply run as a pipe, whose two halves start together, so their order in the log isn't
    # fixed.)
    release_at = first("helm upgrade --install ok3d chart/ok3d")
    applies = [i for i, line in enumerate(log) if line.startswith("kubectl --context k3d-ok3d apply --filename -")]
    assert len(applies) == 5 and max(applies) < release_at
    # The gateway namespace is made first, marked for the release to take over.
    stdin = Path(env["FAKE_LOG"] + ".stdin").read_text()
    assert "name: gateway" in stdin and "meta.helm.sh/release-name: ok3d" in stdin
    assert first("kubectl --context k3d-ok3d --namespace cert-manager create secret") < release_at
    assert "name: monitoring" in stdin and "pod-security.kubernetes.io/enforce: restricted" in stdin

    release = log[first("helm upgrade --install ok3d chart/ok3d")]
    assert "--namespace monitoring" in release
    # Prometheus runs as you, keeps what your settings ask, and nothing runs as root.
    uid, gid = os.getuid(), os.getgid()
    assert f"host.uid={uid},host.gid={gid}" in release
    assert f"securityContext.runAsUser={uid}" in release
    assert "retention=30d" in release and "retentionSize=40GB" in release
    assert (Path(env["FAKE_DATA_ROOT"]) / "prometheus").is_dir()
    assert (Path(env["FAKE_DATA_ROOT"]) / "alertmanager").is_dir()
    assert (Path(env["FAKE_DATA_ROOT"]) / "grafana").is_dir()
    assert "grafana\\.ini.server.root_url=https://grafana.noc.home.arpa:8443/" in release
    # Grafana's queries from a browser carry this Origin, and the gateway rewrites the Host.
    assert "grafana\\.ini.security.csrf_trusted_origins=grafana.noc.home.arpa " in release + " "
    assert f"--set-file tls.caCertificate={env['FAKE_DATA_ROOT']}/certs/ca.crt" in release
    assert f"alertmanagerSpec.securityContext.runAsUser={uid}" in release

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


def test_apply_passes_devices_yaml_when_there_is_one(env: dict[str, str], tmp_path: Path) -> None:
    devices = tmp_path / "devices.yaml"
    devices.write_text("devices: []\n")
    env["OK3D_DEVICES"] = str(devices)
    assert ok3d(env, "apply").returncode == 0
    release = next(line for line in calls(env) if line.startswith("helm upgrade --install ok3d chart/ok3d"))
    assert f"--values {devices}" in release


def test_without_devices_yaml_check_warns_and_apply_goes_on(env: dict[str, str], tmp_path: Path) -> None:
    env["OK3D_DEVICES"] = str(tmp_path / "missing.yaml")
    result = ok3d(env, "check")
    assert result.returncode == 0
    assert "WARN  no devices.yaml" in result.stdout


def test_the_unifi_key_goes_to_kubectl_on_stdin_only(env: dict[str, str], tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("UNIFI_API_KEY='abc123secret'\n")
    dotenv.chmod(0o600)
    env.update(OK3D_ENV=str(dotenv), FAKE_UNIFI="true")
    result = ok3d(env, "apply")
    assert result.returncode == 0, result.stdout + result.stderr
    # Never on a command line, where other users of the machine could see it.
    assert "abc123secret" not in Path(env["FAKE_LOG"]).read_text()
    assert "stdin: abc123secret" in Path(env["FAKE_LOG"] + ".stdin").read_text()


def test_a_dotenv_others_can_read_is_refused(env: dict[str, str], tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("UNIFI_API_KEY=abc123secret\n")
    dotenv.chmod(0o644)
    env.update(OK3D_ENV=str(dotenv), FAKE_UNIFI="true")
    result = ok3d(env, "apply")
    assert result.returncode == 1
    assert "chmod 600" in result.stderr
    assert not any(line.startswith("helm upgrade") for line in calls(env))


def test_unifi_on_with_no_key_is_a_problem_check_finds(env: dict[str, str], tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("UNIFI_API_KEY=\n")
    dotenv.chmod(0o600)
    env.update(OK3D_ENV=str(dotenv), FAKE_UNIFI="true")
    result = ok3d(env, "check")
    assert result.returncode == 1
    assert "UNIFI_API_KEY in .env is empty" in result.stdout


def test_apply_moves_a_0_3_release_out_of_ok3d_system(env: dict[str, str]) -> None:
    env["FAKE_OLD_RELEASE"] = "0"
    assert ok3d(env, "apply").returncode == 0
    log = calls(env)
    uninstall = log.index("helm uninstall ok3d --kube-context k3d-ok3d --namespace ok3d-system --wait")
    assert uninstall < next(i for i, line in enumerate(log) if line.startswith("helm upgrade --install ok3d chart/ok3d"))


def dotenv(tmp_path: Path, env: dict[str, str], text: str) -> None:
    path = tmp_path / ".env"
    path.write_text(text)
    path.chmod(0o600)
    env["OK3D_ENV"] = str(path)


def test_alert_secrets_go_to_kubectl_on_stdin_only_for_what_is_on(env: dict[str, str], tmp_path: Path) -> None:
    dotenv(tmp_path, env, "NTFY_TOPIC=ok3d-7f3k9q\nSMTP_PASSWORD=mail-secret\nDEADMAN_URL=https://hc.example.com/ping/abc\n")
    env.update(FAKE_NTFY="true", FAKE_DEADMAN="true")
    result = ok3d(env, "apply")
    assert result.returncode == 0, result.stdout + result.stderr
    secrets = Path(env["FAKE_LOG"] + ".monitoring.ok3d-alerts").read_text()
    # ntfy's address is built from the server and the topic, with ntfy's Alertmanager template.
    assert "NTFY_URL=https://ntfy.sh/ok3d-7f3k9q?template=alertmanager&tags=ok3d" in secrets
    assert "DEADMAN_URL=https://hc.example.com/ping/abc" in secrets
    # Email is off, so its password stays out, and nothing secret is on a command line.
    assert "mail-secret" not in secrets
    log = Path(env["FAKE_LOG"]).read_text()
    assert "ok3d-7f3k9q" not in log and "hc.example.com" not in log


def test_the_alerts_secret_is_made_even_with_nothing_on(env: dict[str, str]) -> None:
    # Alertmanager mounts it either way.
    assert ok3d(env, "apply").returncode == 0
    assert "NONE=" in Path(env["FAKE_LOG"] + ".monitoring.ok3d-alerts").read_text()


def test_check_finds_a_missing_alert_secret_and_warns_with_no_destination(env: dict[str, str], tmp_path: Path) -> None:
    result = ok3d(env, "check")
    assert "WARN  no alert destination is on" in result.stdout
    dotenv(tmp_path, env, "NTFY_TOPIC=\n")
    env["FAKE_NTFY"] = "true"
    result = ok3d(env, "check")
    assert result.returncode == 1
    assert "alerts.ntfy is on, but NTFY_TOPIC in .env is empty" in result.stdout


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


def test_an_apply_that_works_is_recorded_for_whats_next_and_delete_clears_it(env: dict[str, str]) -> None:
    helper = Path(env["FAKE_DATA_ROOT"]) / "helper"
    assert ok3d(env, "apply").returncode == 0
    assert not helper.exists()  # not made here: the installer makes it
    helper.mkdir()
    assert ok3d(env, "apply").returncode == 0
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n", (helper / "applied").read_text())
    assert ok3d(env, "delete", "--yes").returncode == 0
    assert not (helper / "applied").exists()


def test_an_apply_that_fails_isnt_recorded(env: dict[str, str]) -> None:
    helper = Path(env["FAKE_DATA_ROOT"]) / "helper"
    helper.mkdir()
    result = ok3d(env | {"FAKE_DOCKER_STATUS": "1"}, "apply")
    assert result.returncode != 0
    assert not (helper / "applied").exists()


def test_an_unknown_command_shows_the_usage(env: dict[str, str]) -> None:
    result = ok3d(env, "nosuch")
    assert result.returncode == 2
    assert "./ok3d apply" in result.stderr


def test_version_matches_the_package() -> None:
    from ok3d import __version__

    result = subprocess.run([str(ROOT / "ok3d"), "version"], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == f"ok3d {__version__}"


def test_test_alert_sends_through_alertmanagers_own_amtool(env: dict[str, str]) -> None:
    result = ok3d(env, "test-alert")
    assert result.returncode == 0, result.stderr
    call = next(line for line in calls(env) if "amtool alert add" in line)
    assert "--namespace monitoring exec alertmanager-ok3d-kube-prometheus-stack-alertmanager-0" in call
    assert "OK3DTestAlert severity=warning" in call
    # The summary goes as one quoted matcher value, the form Alertmanager's parser wants.
    assert '--annotation=summary="A test alert from ./ok3d test-alert.' in call
    assert "--end=" in call


def test_the_admin_password_is_made_once_kept_private_and_sent_on_stdin(env: dict[str, str]) -> None:
    assert ok3d(env, "apply").returncode == 0
    kept = Path(env["FAKE_DATA_ROOT"]) / "admin-password"
    assert kept.read_text() == "made-up-admin-password"
    assert stat.S_IMODE(kept.stat().st_mode) == 0o600
    for namespace in ("monitoring", "gateway"):
        secret = Path(env["FAKE_LOG"] + f".{namespace}.ok3d-admin").read_text()
        assert "admin-user=admin" in secret and "admin-password=made-up-admin-password" in secret
    # Never on a command line; the gateway gets only a checksum, to restart when it changes.
    log = Path(env["FAKE_LOG"]).read_text()
    assert "made-up-admin-password" not in log
    assert "gateway.adminChecksum=0123abcd" in log
    # A second apply keeps the same password.
    kept.write_text("still-the-same")
    assert ok3d(env, "apply").returncode == 0
    assert "admin-password=still-the-same" in Path(env["FAKE_LOG"] + ".gateway.ok3d-admin").read_text()


def test_the_admin_password_can_come_from_dotenv(env: dict[str, str], tmp_path: Path) -> None:
    dotenv(tmp_path, env, "OK3D_ADMIN_PASSWORD=chosen-by-you\n")
    result = ok3d(env, "apply")
    assert result.returncode == 0
    assert "admin-password=chosen-by-you" in Path(env["FAKE_LOG"] + ".monitoring.ok3d-admin").read_text()
    assert not (Path(env["FAKE_DATA_ROOT"]) / "admin-password").exists()
    # The page list names Grafana's address: compared part by part, after parsing.
    from urllib.parse import urlsplit

    pages = [urlsplit(word) for line in result.stdout.splitlines() for word in line.split() if "://" in word]
    assert any((p.scheme, p.hostname, p.port, p.path) == ("https", "grafana.noc.home.arpa", 8443, "/") for p in pages)


def test_validate_checks_a_settings_file_that_isnt_in_place(env: dict[str, str], tmp_path: Path) -> None:
    other = tmp_path / "new-settings.yaml"
    other.write_text("settingsVersion: 1\n")
    result = ok3d(env, "validate", "settings", str(other))
    assert result.returncode == 0, result.stderr
    assert f"PASS  the settings in {other}" in result.stdout
    assert any(f"--values {other}" in line for line in calls(env))


def test_validate_checks_devices_against_your_settings(env: dict[str, str], tmp_path: Path) -> None:
    other = tmp_path / "new-devices.yaml"
    other.write_text("devices: []\n")
    result = ok3d(env, "validate", "devices", str(other))
    assert result.returncode == 0, result.stderr
    assert any(f"--values {env['OK3D_SETTINGS']} --values {other}" in line for line in calls(env))


@pytest.mark.parametrize("args", [["validate"], ["validate", "settings"], ["validate", "secrets", "x"],
                                  ["validate", "settings", "/no/such/file"]])  # fmt: skip
def test_validate_needs_a_kind_and_a_file(env: dict[str, str], args: list[str]) -> None:
    assert ok3d(env, *args).returncode == 2


def test_check_reads_settings_and_devices_through_the_section_check(env: dict[str, str], tmp_path: Path) -> None:
    devices = tmp_path / "devices.yaml"
    devices.write_text("devices: []\n")
    ok3d({**env, "OK3D_DEVICES": str(devices)}, "check")
    log = calls(env)
    assert any(line.startswith(f"helm template ok3d-files chart/ok3d-files/settings --values {env['OK3D_SETTINGS']}") for line in log)
    assert any(line.startswith(f"helm template ok3d-files chart/ok3d-files/devices --values {devices}") for line in log)



@pytest.fixture
def linux(env: dict[str, str], tmp_path: Path) -> dict[str, str]:
    """A Linux machine with systemd, its user config under tmp_path."""
    return {**env, "FAKE_UNAME": "Linux", "XDG_CONFIG_HOME": str(tmp_path / "config")}


def test_install_sets_up_the_helper_and_the_dashboard(linux: dict[str, str], tmp_path: Path) -> None:
    result = ok3d(linux, "install")
    assert result.returncode == 0, result.stdout + result.stderr
    data = Path(linux["FAKE_DATA_ROOT"])
    for folder in ("dashboard", "dashboard/outbox", "dashboard/tls", "helper"):
        assert stat.S_IMODE((data / folder).stat().st_mode) == 0o700, folder
    unit = (tmp_path / "config" / "systemd" / "user" / "ok3d-helper.service").read_text()
    assert f"ExecStart=/usr/bin/python3 -I {ROOT}/src/ok3d/helper.py watch --ok3d-dir {ROOT} --data-root {data}" in unit
    for placeholder in ("@DIR@", "@DATA_ROOT@", "@PATH@"):
        assert placeholder not in unit
    log = calls(linux)
    assert "systemctl --user daemon-reload" in log
    assert "systemctl --user restart ok3d-helper" in log
    run = next(line for line in log if line.startswith("docker run"))
    from ok3d import __version__

    # A release pulls its own version's image; between releases, main's.
    image = "ghcr.io/southsidedean/ok3d-dashboard:" + ("main" if "dev" in __version__ else __version__)
    for part in ("--name ok3d-dashboard", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges",
                 "--publish 0.0.0.0:8444:8444", f"--volume {data}/dashboard:/state",
                 f"--volume {data}/helper:/helper:ro", image,
                 "--origin https://dashboard.noc.home.arpa:8444"):  # fmt: skip
        assert part in run, part
    assert f"--user {os.getuid()}:{os.getgid()}" in run
    assert "Done. Open the Dashboard at https://dashboard.noc.home.arpa:8444/" in result.stdout.splitlines()
    assert "kxq7-m2pa-9fht-3bnd" not in result.stdout  # not a terminal (test_the_password_is_shown_only_on_a_terminal)


def test_install_issues_the_dashboards_certificate_for_its_name(linux: dict[str, str]) -> None:
    ok3d(linux, "install")
    issue = next(line for line in calls(linux) if line.startswith("openssl x509 -req"))
    assert "-days 397" in issue
    assert "-set_serial 0x" in issue
    ext = Path(linux["FAKE_LOG"] + ".ext").read_text()
    assert "subjectAltName=DNS:dashboard.noc.home.arpa\n" in ext
    assert "basicConstraints=critical,CA:FALSE" in ext
    # Made where the Dashboard's container can't reach, and only the result moved into tls/.
    data = linux["FAKE_DATA_ROOT"]
    assert f"-extfile {data}/certs/issue." in issue
    assert "-CAserial" not in issue
    assert sorted(os.listdir(Path(data) / "dashboard" / "tls")) == ["dashboard.crt", "dashboard.key"]
    assert [n for n in os.listdir(Path(data) / "certs") if n.startswith("issue.")] == []


def test_a_new_certificate_authority_vouches_for_no_ip_address(linux: dict[str, str]) -> None:
    ok3d(linux, "install")
    make = next(line for line in calls(linux) if line.startswith("openssl req -x509"))
    assert "excluded;IP:0.0.0.0/0.0.0.0" in make


def test_install_replaces_links_in_tls_instead_of_following_them(linux: dict[str, str], tmp_path: Path) -> None:
    tls = Path(linux["FAKE_DATA_ROOT"]) / "dashboard" / "tls"
    tls.mkdir(parents=True)
    victim = tmp_path / "authorized_keys"
    victim.write_text("mine\n")
    (tls / "dashboard.key").symlink_to(victim)
    ok3d(linux, "install")
    assert victim.read_text() == "mine\n"
    assert not (tls / "dashboard.key").is_symlink()


def test_install_refuses_a_tls_folder_that_is_a_link(linux: dict[str, str], tmp_path: Path) -> None:
    dashboard = Path(linux["FAKE_DATA_ROOT"]) / "dashboard"
    dashboard.mkdir()
    (tmp_path / "elsewhere").mkdir()
    (dashboard / "tls").symlink_to(tmp_path / "elsewhere")
    result = ok3d(linux, "install")
    assert result.returncode == 1
    assert "isn't a folder" in result.stderr


def test_a_failed_pull_leaves_the_running_dashboard(linux: dict[str, str]) -> None:
    result = ok3d({**linux, "FAKE_PULL_STATUS": "1"}, "install")
    assert result.returncode == 1
    assert "left as it was" in result.stderr
    assert not any(line.startswith("docker rm") for line in calls(linux))


def on_a_terminal(env: dict[str, str], *args: str) -> str:
    """What ./ok3d prints when its output is a terminal, as when you run the installer yourself."""
    main, side = pty.openpty()
    try:
        proc = subprocess.Popen([str(ROOT / "ok3d"), *args], stdin=subprocess.DEVNULL, stdout=side,
                                stderr=subprocess.PIPE, env=env)  # fmt: skip
    finally:
        os.close(side)
    out = b""
    try:
        while True:
            try:
                chunk = os.read(main, 4096)
            except OSError:  # Linux says EIO once the program has gone
                break
            if not chunk:
                break
            out += chunk
        _, errors = proc.communicate(timeout=30)
    finally:
        proc.kill()
        os.close(main)
    assert proc.returncode == 0, out.decode() + errors.decode()
    return out.decode()


def test_the_password_is_shown_on_first_install_only(linux: dict[str, str]) -> None:
    assert "kxq7-m2pa-9fht-3bnd" in on_a_terminal(linux, "install")
    again = on_a_terminal(linux, "install")
    assert "kxq7-m2pa-9fht-3bnd" not in again
    assert "Its password is in" in again


def test_the_password_is_shown_only_on_a_terminal(linux: dict[str, str]) -> None:
    # Read by an AI assistant, a log, or another program, the output says where it is instead.
    result = ok3d(linux, "install")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "kxq7-m2pa-9fht-3bnd" not in result.stdout
    assert "Its password is in" in result.stdout


def test_install_refuses_one_port_for_both(linux: dict[str, str]) -> None:
    result = ok3d({**linux, "FAKE_DASHBOARD_PORT": "8443"}, "install")
    assert result.returncode == 1
    assert "need a port each" in result.stderr


def test_install_refuses_a_path_the_service_file_cant_hold(linux: dict[str, str]) -> None:
    result = ok3d({**linux, "PATH": linux["PATH"] + ':/opt/"odd'}, "install")
    assert result.returncode == 1
    assert "PATH has a quote" in result.stderr


def test_install_escapes_percent_signs_for_systemd(linux: dict[str, str], tmp_path: Path) -> None:
    ok3d({**linux, "PATH": linux["PATH"] + ":/opt/100%"}, "install")
    unit = (tmp_path / "config" / "systemd" / "user" / "ok3d-helper.service").read_text()
    assert "/opt/100%%" in unit


def test_install_says_how_to_keep_the_helper_running_after_logout(linux: dict[str, str]) -> None:
    result = ok3d({**linux, "FAKE_LINGER": "no"}, "install")
    assert "sudo loginctl enable-linger" in result.stdout


def test_install_uses_the_image_you_name(linux: dict[str, str]) -> None:
    ok3d({**linux, "OK3D_DASHBOARD_IMAGE": "ok3d-dashboard:local"}, "install")
    assert any(line.startswith("docker run") and " ok3d-dashboard:local " in line for line in calls(linux))


def test_install_needs_linux_with_systemd(env: dict[str, str]) -> None:
    result = ok3d(env, "install")
    assert result.returncode == 1
    assert "needs Linux with systemd" in result.stderr


def test_install_needs_a_data_root(linux: dict[str, str]) -> None:
    Path(linux["FAKE_DATA_ROOT"]).rmdir()
    result = ok3d(linux, "install")
    assert result.returncode == 1
    assert not any(line.startswith("docker run") for line in calls(linux))


# ./ok3d upgrade, with a real git repository standing in for ok3d's releases: v0.5.0 is this
# ok3d, and v0.5.1 is a stand-in whose ok3d records what it's asked to run (failing a
# command named in FAKE_NEW_FAIL). Tags are signed with a key made for the test.

NEW_OK3D = r"""#!/bin/sh
echo "new ok3d $*" >>"$FAKE_LOG"
# A change to one of ok3d's own files, so moving back fails.
[ -z "${FAKE_NEW_DIRTY:-}" ] || echo "# changed" >>src/ok3d/__init__.py
[ "$1" != "${FAKE_NEW_FAIL:-}" ] || { echo "the new $1 failed"; exit 1; }
"""


def git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout


def git_env(tmp_path: Path) -> dict[str, str]:
    """git without the machine's own settings (a signing key, a signers file), as a made-up person."""
    return {**os.environ, "GIT_CONFIG_GLOBAL": str(tmp_path / "no-gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"}  # fmt: skip


def signing_key(tmp_path: Path, name: str) -> Path:
    key = tmp_path / name
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "", "-f", str(key)], check=True)
    return key


@pytest.fixture
def releases(linux: dict[str, str], tmp_path: Path) -> dict[str, str]:
    """A releases repository and a checkout of it at v0.5.0, and the env to upgrade it with."""
    genv = git_env(tmp_path)
    key = signing_key(tmp_path, "release-key")
    other = signing_key(tmp_path, "other-key")
    repo = tmp_path / "releases"
    (repo / "src" / "ok3d").mkdir(parents=True)
    (repo / "deploy").mkdir()
    (repo / "deploy" / "release-signers").write_text(
        f'ok3d-release namespaces="git" {key.with_suffix(".pub").read_text().split()[0]} '
        f"{key.with_suffix('.pub').read_text().split()[1]}\n"
    )
    shutil.copy(ROOT / "ok3d", repo / "ok3d")
    shutil.copy(ROOT / "deploy" / "ok3d-helper.service", repo / "deploy")
    git(repo, "init", "--quiet", "--initial-branch=main", env=genv)

    def commit(version: str, ok3d_text: str | None = None) -> None:
        (repo / "src" / "ok3d" / "__init__.py").write_text(f'__version__ = "{version}"\n')
        if ok3d_text is not None:
            (repo / "ok3d").write_text(ok3d_text)
        git(repo, "add", "-A", env=genv)
        git(repo, "commit", "--quiet", "-m", version, env=genv)

    def tag(name: str, with_key: Path | None) -> None:
        if with_key is None:
            git(repo, "tag", "-a", name, "-m", name, env=genv)
        else:
            git(repo, "-c", "gpg.format=ssh", "-c", f"user.signingkey={with_key}", "tag", "-s", name, "-m", name, env=genv)

    commit("0.5.0")
    tag("v0.5.0", key)
    commit("0.5.1.dev0")
    git(repo, "branch", "dev", env=genv)
    commit("0.5.1", NEW_OK3D)
    tag("v0.5.1", key)
    commit("0.5.2", NEW_OK3D)
    tag("v0.5.2", None)  # not signed
    commit("0.5.3", NEW_OK3D)
    tag("v0.5.3", other)  # signed, by a key that isn't in deploy/release-signers
    # v0.5.1's signed tag, pushed again under a newer name by someone without the key.
    git(repo, "update-ref", "refs/tags/v0.5.4", git(repo, "rev-parse", "v0.5.1", env=genv).strip(), env=genv)
    commit("0.5.4", NEW_OK3D)
    tag("v0.5.5", key)  # properly signed, but its ok3d says it's 0.5.4
    tag("v0.9.0-rc1", key)  # a test release, never offered
    git(repo, "checkout", "--quiet", "dev", env=genv)
    checkout = tmp_path / "checkout"
    git(tmp_path, "clone", "--quiet", "--branch", "v0.5.0", str(repo), str(checkout), env=genv)
    for tag_name in ("v0.5.1", "v0.5.2", "v0.5.3", "v0.5.4", "v0.5.5", "v0.9.0-rc1"):  # as if they weren't out yet
        git(checkout, "tag", "--delete", tag_name, env=genv)
    data = Path(linux["FAKE_DATA_ROOT"])
    for part in ("helper", "certs", "grafana", "alertmanager", "prometheus"):
        (data / part).mkdir()
    (data / "grafana" / "grafana.db").write_text("dashboards")
    (data / "prometheus" / "big").write_text("history")
    git_only = {k: v for k, v in genv.items() if k.startswith("GIT_")}  # the stand-ins' PATH stays
    return {**linux, **git_only, "OK3D_REPO": str(repo), "CHECKOUT": str(checkout)}


def upgrade(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(Path(env["CHECKOUT"]) / "ok3d"), "upgrade", *args],
                          capture_output=True, text=True, env=env, check=False)  # fmt: skip


def at(env: dict[str, str]) -> str:
    return (Path(env["CHECKOUT"]) / "src" / "ok3d" / "__init__.py").read_text()


def note(env: dict[str, str], name: str) -> dict[str, str]:
    text = (Path(env["FAKE_DATA_ROOT"]) / "helper" / name).read_text()
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def test_upgrade_says_which_release_is_newer(releases: dict[str, str]) -> None:
    result = upgrade(releases)
    assert result.returncode == 0, result.stderr
    assert "ok3d v0.5.5 is out (this is ok3d 0.5.0)." in result.stdout  # not v0.9.0-rc1
    assert "./ok3d upgrade v0.5.5" in result.stdout
    assert note(releases, "newest-release")["newest"] == "v0.5.5"


def test_upgrade_moves_to_a_signed_release_and_makes_the_cluster_again(releases: dict[str, str]) -> None:
    result = upgrade(releases, "v0.5.1", "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"0.5.1"' in at(releases)
    assert [c for c in calls(releases) if c.startswith("new ok3d")] == [
        "new ok3d check", "new ok3d install", "new ok3d delete --yes", "new ok3d apply"]  # fmt: skip
    data = Path(releases["FAKE_DATA_ROOT"])
    (archive,) = (data / "backups").glob("before-v0.5.1-*.tar.gz")
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert "grafana/grafana.db" in names and "certs" in names and "alertmanager" in names
    assert not any(n.startswith("prometheus") for n in names)
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    (saved,) = (Path(releases["CHECKOUT"]) / "local" / "backups").glob("before-v0.5.1-*")
    assert (saved / "settings.yaml").read_text() == "settingsVersion: 1\n"
    done = note(releases, "upgrade")
    assert {"from": "0.5.0", "to": "v0.5.1", "state": "finished"}.items() <= done.items()
    output = (data / "helper" / "upgrade-output").read_text()
    assert "== Checking v0.5.1's signature" in output and "Upgraded from ok3d 0.5.0 to v0.5.1." in output
    with (Path(releases["CHECKOUT"]) / "local" / "upgrading").open() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # let go of: no one holds it now


@pytest.mark.parametrize("tag", ["v0.5.2", "v0.5.3"])
def test_upgrade_refuses_a_release_without_a_known_signature(releases: dict[str, str], tag: str) -> None:
    result = upgrade(releases, tag, "--yes")
    assert result.returncode == 1
    assert "isn't signed by a key in deploy/release-signers" in result.stderr
    assert '"0.5.0"' in at(releases)
    assert not any(c.startswith(("new ok3d", "k3d cluster delete")) for c in calls(releases))
    assert note(releases, "upgrade")["state"] == "failed"


def test_a_failed_check_moves_back_and_leaves_the_cluster(releases: dict[str, str]) -> None:
    result = upgrade(releases | {"FAKE_NEW_FAIL": "check"}, "v0.5.1", "--yes")
    assert result.returncode == 1
    assert "check found problems" in result.stderr
    assert '"0.5.0"' in at(releases)
    assert [c for c in calls(releases) if c.startswith("new ok3d")] == ["new ok3d check"]
    assert note(releases, "upgrade")["state"] == "failed"


def test_a_failed_install_moves_back_and_installs_the_old_release_again(releases: dict[str, str]) -> None:
    result = upgrade(releases | {"FAKE_NEW_FAIL": "install"}, "v0.5.1", "--yes")
    assert result.returncode == 1
    assert '"0.5.0"' in at(releases)
    log = calls(releases)
    assert [c for c in log if c.startswith("new ok3d")] == ["new ok3d check", "new ok3d install"]
    after = log[log.index("new ok3d install") :]
    assert any(c.startswith("docker run") for c in after)  # 0.5.0's own install, again
    assert not any(c.startswith("new ok3d delete") for c in log)


def test_a_failed_apply_stops_and_says_so(releases: dict[str, str]) -> None:
    result = upgrade(releases | {"FAKE_NEW_FAIL": "apply"}, "v0.5.1", "--yes")
    assert result.returncode == 1
    assert "./ok3d apply failed" in result.stderr
    assert {"state": "failed", "to": "v0.5.1"}.items() <= note(releases, "upgrade").items()


@pytest.mark.parametrize("tag", ["v0.5.0", "v0.4.0"])
def test_upgrade_only_moves_forward(releases: dict[str, str], tag: str) -> None:
    result = upgrade(releases, tag, "--yes")
    assert result.returncode == 1
    assert "only moves forward" in result.stderr


@pytest.mark.parametrize("tag", ["0.5.1", "v0.5", "v0.5.1.1", "vv0.5.1", "v0..5", "v0.5.1;reboot",
                                 "v0.5.1\nv", "v0.5.", "--yes", "v123456789.123456789.0"])  # fmt: skip
def test_upgrade_takes_only_a_release_tag(releases: dict[str, str], tag: str) -> None:
    result = upgrade(releases, tag, "--yes")
    assert result.returncode == 2
    assert "a release tag such as v0.5.1" in result.stderr


def test_upgrade_needs_a_yes(releases: dict[str, str]) -> None:
    result = upgrade(releases, "v0.5.1")
    assert result.returncode == 1
    assert "--yes" in result.stderr
    assert '"0.5.0"' in at(releases)


def test_upgrade_wont_move_a_checkout_with_your_changes(releases: dict[str, str]) -> None:
    (Path(releases["CHECKOUT"]) / "ok3d").write_text((Path(releases["CHECKOUT"]) / "ok3d").read_text() + "\n# mine\n")
    result = upgrade(releases, "v0.5.1", "--yes")
    assert result.returncode == 1
    assert "changes of yours" in result.stderr


def test_one_upgrade_at_a_time(releases: dict[str, str]) -> None:
    lock = Path(releases["CHECKOUT"]) / "local" / "upgrading"
    lock.parent.mkdir(parents=True)
    with lock.open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)  # as an upgrade that's running holds it
        result = upgrade(releases, "v0.5.1", "--yes")
    assert result.returncode == 1
    assert "An upgrade is running already" in result.stderr
    assert '"0.5.0"' in at(releases)


def test_a_lock_file_left_behind_counts_for_nothing(releases: dict[str, str]) -> None:
    lock = Path(releases["CHECKOUT"]) / "local" / "upgrading"
    lock.parent.mkdir(parents=True)
    lock.write_text("")  # left by an upgrade that ended, however it ended: nothing holds it
    result = upgrade(releases, "v0.5.1", "--yes")
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_signed_tag_under_another_name_isnt_taken(releases: dict[str, str]) -> None:
    result = upgrade(releases, "v0.5.4", "--yes")
    assert result.returncode == 1
    assert "The tag called v0.5.4 is really v0.5.1." in result.stdout
    assert '"0.5.0"' in at(releases)


def test_a_release_whose_ok3d_says_another_version_is_left(releases: dict[str, str]) -> None:
    result = upgrade(releases, "v0.5.5", "--yes")
    assert result.returncode == 1
    assert "v0.5.5 says it's ok3d 0.5.4, not 0.5.5" in result.stderr
    assert '"0.5.0"' in at(releases)
    assert not any(c.startswith("new ok3d") for c in calls(releases))


def test_the_signed_commit_is_checked_out_even_with_a_branch_of_the_same_name(releases: dict[str, str]) -> None:
    checkout = Path(releases["CHECKOUT"])
    git(checkout, "branch", "v0.5.1", "origin/dev", env=releases)  # a branch called v0.5.1, at 0.5.1.dev0
    assert upgrade(releases, "v0.5.1", "--yes").returncode == 0
    assert '"0.5.1"' in at(releases)
    assert git(checkout, "rev-parse", "HEAD", env=releases) == git(checkout, "rev-parse", "refs/tags/v0.5.1^{commit}", env=releases)


def test_a_refusal_shows_on_the_dashboard(releases: dict[str, str]) -> None:
    script = Path(releases["CHECKOUT"]) / "ok3d"
    script.write_text(script.read_text() + "\n# mine\n")
    result = upgrade(releases | {"OK3D_UPGRADE_FROM_DASHBOARD": "yes"}, "v0.5.1", "--yes")
    assert result.returncode == 1
    told = note(releases, "upgrade")
    assert {"from": "0.5.0", "to": "v0.5.1", "state": "failed"}.items() <= told.items()
    assert "changes of yours" in told["step"]
    assert "changes of yours" in (Path(releases["FAKE_DATA_ROOT"]) / "helper" / "upgrade-output").read_text()


def test_upgrade_waits_for_a_request_the_helper_is_carrying_out(releases: dict[str, str]) -> None:
    result_file = Path(releases["FAKE_DATA_ROOT"]) / "helper" / "result"
    result_file.write_text("id=0123456789abcdef\naction=apply\nstate=running\n\n")
    result = upgrade(releases | {"OK3D_BUSY_WAIT": "0"}, "v0.5.1", "--yes")  # a real Apply: still running
    assert result.returncode == 1
    assert "carrying out a request from the Dashboard" in result.stderr
    # The helper's own answer while it starts an upgrade doesn't count.
    result_file.write_text("id=0123456789abcdef\naction=upgrade\nstate=running\n\n")
    assert upgrade(releases, "v0.5.1", "--yes").returncode == 0


def test_a_failed_check_moves_back_to_the_branch_you_were_on(releases: dict[str, str]) -> None:
    checkout = Path(releases["CHECKOUT"])
    git(checkout, "checkout", "--quiet", "-b", "mine", env=releases)
    result = upgrade(releases | {"FAKE_NEW_FAIL": "check"}, "v0.5.1", "--yes")
    assert result.returncode == 1
    assert git(checkout, "symbolic-ref", "--short", "HEAD", env=releases).strip() == "mine"
    assert note(releases, "upgrade")["state"] == "failed"


def test_only_the_last_three_settings_backups_are_kept(releases: dict[str, str]) -> None:
    backups = Path(releases["CHECKOUT"]) / "local" / "backups"
    for n in range(4):
        old = backups / f"before-v0.5.1-2026010{n}T000000Z"
        old.mkdir(parents=True)
        os.utime(old, (n, n))
    assert upgrade(releases | {"FAKE_NEW_FAIL": "check"}, "v0.5.1", "--yes").returncode == 1
    kept = sorted(p.name for p in backups.glob("before-*"))
    assert len(kept) == 3 and "before-v0.5.1-20260100T000000Z" not in kept


def test_a_development_version_comes_before_its_release(releases: dict[str, str]) -> None:
    git(Path(releases["CHECKOUT"]), "fetch", "--quiet", "origin", "dev", env=releases)
    git(Path(releases["CHECKOUT"]), "checkout", "--quiet", "FETCH_HEAD", env=releases)
    assert '"0.5.1.dev0"' in at(releases)
    result = upgrade(releases, "v0.5.1", "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"0.5.1"' in at(releases)


def test_a_refusal_on_the_server_leaves_homes_record_alone(releases: dict[str, str]) -> None:
    record = Path(releases["FAKE_DATA_ROOT"]) / "helper" / "upgrade"
    record.write_text("from=0.4.0\nto=v0.5.0\nstate=finished\n")
    assert upgrade(releases, "v0.4.0", "--yes").returncode == 1  # a typo, from a terminal
    assert record.read_text() == "from=0.4.0\nto=v0.5.0\nstate=finished\n"


def test_a_refusal_never_writes_over_a_running_upgrades_record(releases: dict[str, str]) -> None:
    helper_dir = Path(releases["FAKE_DATA_ROOT"]) / "helper"
    (helper_dir / "upgrade").write_text("from=0.5.0\nto=v0.5.1\nstate=running\nstep=Making the cluster again\n")
    (helper_dir / "upgrade-output").write_text("== Moving to v0.5.1\n")
    lock = Path(releases["CHECKOUT"]) / "local" / "upgrading"
    lock.parent.mkdir(parents=True)
    with lock.open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)  # that upgrade, running
        result = upgrade(releases | {"OK3D_UPGRADE_FROM_DASHBOARD": "yes"}, "v0.4.0", "--yes")
    assert "An upgrade is running already" in result.stderr
    assert "state=running" in (helper_dir / "upgrade").read_text()
    assert (helper_dir / "upgrade-output").read_text() == "== Moving to v0.5.1\n"


def test_the_lock_is_held_while_it_asks(releases: dict[str, str]) -> None:
    # Held from before the check for a request the helper is carrying out until the end, so
    # the helper can't start an Apply while you're deciding.
    main, side = pty.openpty()
    proc = subprocess.Popen([str(Path(releases["CHECKOUT"]) / "ok3d"), "upgrade", "v0.5.1"], stdin=side,
                            stdout=side, stderr=subprocess.PIPE, env=releases)  # fmt: skip
    try:
        out = b""
        while b"Type v0.5.1" not in out:
            out += os.read(main, 4096)
        with (Path(releases["CHECKOUT"]) / "local" / "upgrading").open() as lock, pytest.raises(BlockingIOError):
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        os.write(main, b"no\n")
        assert proc.wait(timeout=30) == 1
    finally:
        proc.kill()
        os.close(main)
        os.close(side)
    assert '"0.5.0"' in at(releases)


def test_a_failed_move_back_says_so(releases: dict[str, str]) -> None:
    result = upgrade(releases | {"FAKE_NEW_FAIL": "check", "FAKE_NEW_DIRTY": "yes"}, "v0.5.1", "--yes")
    assert result.returncode == 1
    assert "Moving back to 0.5.0 failed too" in result.stderr
    assert "Moving back to 0.5.0 failed too" in note(releases, "upgrade")["step"]


def sign(releases: dict[str, str], tmp_path: Path, name: str, target: str, version: str) -> str:
    """A tag called name, signed with the release key, for a new commit saying version (or,
    with target "tree", for that commit's tree); returns the tag object's id."""
    repo = Path(releases["OK3D_REPO"])
    git(repo, "checkout", "--quiet", "v0.5.1", env=releases)
    (repo / "src" / "ok3d" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    git(repo, "commit", "--quiet", "-am", version, env=releases)
    git(repo, "-c", "gpg.format=ssh", "-c", f"user.signingkey={tmp_path / 'release-key'}", "tag", "-s", name,
        "-m", name, "HEAD^{tree}" if target == "tree" else "HEAD", env=releases)  # fmt: skip
    return git(repo, "rev-parse", f"refs/tags/{name}", env=releases).strip()


def test_the_tag_name_is_matched_exactly(releases: dict[str, str], tmp_path: Path) -> None:
    # A signed tag called v0a5a6 (whose name would match v0.5.6 as a pattern), published as v0.5.6.
    made = sign(releases, tmp_path, "v0a5a6", "commit", "0.5.6")
    git(Path(releases["OK3D_REPO"]), "update-ref", "refs/tags/v0.5.6", made, env=releases)
    result = upgrade(releases, "v0.5.6", "--yes")
    assert result.returncode == 1
    assert "The tag called v0.5.6 is really v0a5a6." in result.stdout
    assert '"0.5.0"' in at(releases)


def test_a_signed_tag_of_something_other_than_a_commit_is_refused(releases: dict[str, str], tmp_path: Path) -> None:
    sign(releases, tmp_path, "v0.5.7", "tree", "0.5.7")
    result = upgrade(releases, "v0.5.7", "--yes")
    assert result.returncode == 1
    assert "v0.5.7 is a tag for something other than a commit." in result.stdout


def test_a_tag_here_that_isnt_the_one_there_is_refused_and_says_why(releases: dict[str, str]) -> None:
    checkout = Path(releases["CHECKOUT"])
    git(checkout, "tag", "v0.5.1", env=releases)  # a different v0.5.1, already here
    result = upgrade(releases, "v0.5.1", "--yes")
    assert result.returncode == 1
    assert "would clobber existing tag" in result.stdout
    assert "would clobber existing tag" in (Path(releases["FAKE_DATA_ROOT"]) / "helper" / "upgrade-output").read_text()


def test_a_failed_check_never_reinstalls_whatever_the_environment_says(releases: dict[str, str]) -> None:
    result = upgrade(releases | {"FAKE_NEW_FAIL": "check", "reinstall": "yes"}, "v0.5.1", "--yes")
    assert result.returncode == 1
    log = calls(releases)
    assert not any(c.startswith("docker run") for c in log[log.index("new ok3d check"):])


def test_a_request_the_helper_refuses_a_moment_later_doesnt_stop_the_upgrade(releases: dict[str, str],
                                                                             tmp_path: Path) -> None:  # fmt: skip
    # A Check that arrived just now says it's running, then the helper sees the upgrade's lock
    # and refuses it: the upgrade reads the answer again, and goes on. The stand-in sleep is
    # where the helper refuses it, so the test doesn't depend on timing.
    result_file = Path(releases["FAKE_DATA_ROOT"]) / "helper" / "result"
    result_file.write_text("id=0123456789abcdef\naction=check\nstate=running\n\n")
    waits = tmp_path / "waits"
    waits.mkdir()
    (waits / "sleep").write_text('#!/bin/sh\necho "sleep $*" >>"$FAKE_LOG"\n'
                                 'printf \'id=0123456789abcdef\\nstate=refused\\n\\n\' >"$FAKE_RESULT"\n')  # fmt: skip
    (waits / "sleep").chmod(0o755)
    env = releases | {"PATH": f"{waits}:{releases['PATH']}", "FAKE_RESULT": str(result_file), "OK3D_BUSY_WAIT": "5"}
    result = upgrade(env, "v0.5.1", "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "sleep 1" in calls(releases)  # it waited, and read the answer again


def test_a_request_that_stays_running_is_refused_after_the_wait(releases: dict[str, str], tmp_path: Path) -> None:
    # A real Apply stays running: the upgrade reads it again once a second, then refuses, and
    # never waits longer than it's allowed.
    result_file = Path(releases["FAKE_DATA_ROOT"]) / "helper" / "result"
    result_file.write_text("id=0123456789abcdef\naction=apply\nstate=running\n\n")
    waits = tmp_path / "waits"
    waits.mkdir()
    (waits / "sleep").write_text('#!/bin/sh\necho "sleep $*" >>"$FAKE_LOG"\n')
    (waits / "sleep").chmod(0o755)
    result = upgrade(releases | {"PATH": f"{waits}:{releases['PATH']}", "OK3D_BUSY_WAIT": "2"}, "v0.5.1", "--yes")
    assert result.returncode == 1
    assert "carrying out a request from the Dashboard" in result.stderr
    assert [c for c in calls(releases) if c.startswith("sleep")] == ["sleep 1", "sleep 1"]
    assert '"0.5.0"' in at(releases)



# Check says what Apply would change in a running cluster, and Apply asks first on a terminal.

def deployed(env: dict[str, str], tmp_path: Path, replicas: int) -> dict[str, str]:
    """A running cluster with Grafana deployed, and a dry run with replicas Grafanas."""
    grafana = "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: ok3d-grafana\n  namespace: monitoring\nspec:\n  replicas: {}\n"
    (tmp_path / "manifest").write_text("---\n" + grafana.format(1))
    (tmp_path / "dry-run").write_text("NAME: ok3d\nMANIFEST:\n---\n" + grafana.format(replicas))
    (Path(env["FAKE_DATA_ROOT"]) / "admin-password").write_text("made-up-admin-password")
    (Path(env["FAKE_DATA_ROOT"]) / "helper").mkdir(exist_ok=True)
    return env | {"FAKE_CLUSTER_GET": "0", "FAKE_MANIFEST": str(tmp_path / "manifest"),
                  "FAKE_DRY_RUN": str(tmp_path / "dry-run")}  # fmt: skip


def test_check_says_what_apply_would_restart(env: dict[str, str], tmp_path: Path) -> None:
    running = deployed(env, tmp_path, 2)
    result = ok3d(running, "check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "What Apply will change:\n  restart  Grafana" in result.stdout
    plan = (Path(env["FAKE_DATA_ROOT"]) / "helper" / "apply-plan").read_text()
    assert "state=changes\nrestart=Grafana\nother=0\n" in plan


def test_check_says_when_apply_would_change_nothing_or_make_the_cluster(env: dict[str, str], tmp_path: Path) -> None:
    assert "Apply will change nothing that's running." in ok3d(deployed(env, tmp_path, 1), "check").stdout
    assert "Apply will make what's missing and deploy ok3d." in ok3d(env, "check").stdout


def test_the_dry_run_uses_applys_own_arguments(env: dict[str, str], tmp_path: Path) -> None:
    running = deployed(env, tmp_path, 1)
    assert ok3d(running, "apply").returncode == 0
    log = calls(running)
    dry = next(c for c in log if "--dry-run=server" in c)
    real = next(c for c in log if c.startswith("helm upgrade --install ok3d chart/ok3d"))
    assert dry.removeprefix("helm upgrade ok3d chart/ok3d ").split(" --kube-context")[0] == \
        real.removeprefix("helm upgrade --install ok3d chart/ok3d ").split(" --kube-context")[0]


def test_check_changes_nothing_while_it_looks(env: dict[str, str], tmp_path: Path) -> None:
    running = deployed(env, tmp_path, 2)
    ok3d(running, "check")
    assert not any(c.startswith(("helm upgrade --install", "kubectl", "k3d cluster create")) for c in calls(running))


def test_without_the_admin_password_check_cant_tell(env: dict[str, str], tmp_path: Path) -> None:
    running = deployed(env, tmp_path, 1)
    (Path(env["FAKE_DATA_ROOT"]) / "admin-password").unlink()
    result = ok3d(running, "check")
    assert "Check couldn't tell what Apply would change" in result.stdout
    assert not (Path(env["FAKE_DATA_ROOT"]) / "admin-password").exists()  # Check doesn't make it


def apply_on_a_terminal(env: dict[str, str], answer: bytes, *args: str) -> tuple[int, str]:
    main, side = pty.openpty()
    try:
        proc = subprocess.Popen([str(ROOT / "ok3d"), "apply", *args], stdin=side, stdout=side, stderr=side, env=env)
    finally:
        os.close(side)  # only the program holds it now, so a read ends when the program does
    out = b""
    try:
        while True:
            try:
                chunk = os.read(main, 4096)
            except OSError:  # Linux says EIO once the program has gone
                break
            if not chunk:
                break
            out += chunk
            if b"Go ahead?" in out and answer:
                os.write(main, answer)
                answer = b""
        status = proc.wait(timeout=60)
    finally:
        proc.kill()
        os.close(main)
    return status, out.decode()


def test_apply_asks_first_on_a_terminal_and_no_means_no(env: dict[str, str], tmp_path: Path) -> None:
    running = deployed(env, tmp_path, 2)
    status, out = apply_on_a_terminal(running, b"n\n")
    assert status == 1 and "restart  Grafana" in out
    assert not any(c.startswith("helm upgrade --install ok3d ") for c in calls(running))


def test_apply_goes_ahead_on_yes(env: dict[str, str], tmp_path: Path) -> None:
    running = deployed(env, tmp_path, 2)
    status, _ = apply_on_a_terminal(running, b"y\n")
    assert status == 0
    assert any(c.startswith("helm upgrade --install ok3d ") for c in calls(running))


def test_apply_with_yes_or_from_another_program_doesnt_ask(env: dict[str, str], tmp_path: Path) -> None:
    running = deployed(env, tmp_path, 2)
    assert ok3d(running, "apply").returncode == 0  # not a terminal: the helper, an upgrade
    status, out = apply_on_a_terminal(running, b"", "--yes")
    assert status == 0 and "Go ahead?" not in out
