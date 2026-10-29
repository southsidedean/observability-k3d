"""The ok3d command, run for real with stand-ins for docker, k3d, helm, kubectl, openssl, and
uname: what it checks, what it makes, in what order, and what it refuses. The stand-ins write
each call to a log, so a test can see exactly what ok3d would have run. (The real thing is
tested on the test VM: PLAN.md, "The test VM".)
"""

from __future__ import annotations

import os
import pty
import re
import stat
import subprocess
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
