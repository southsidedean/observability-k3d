"""The charts, rendered by the real Helm: they lint and render with the example settings, every
setting is described, the schema refuses what can't work, and what they render keeps ok3d's
rules (restricted namespaces, the certificate for every page). Skipped where Helm isn't
installed; CI installs it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHART = ROOT / "chart" / "ok3d"
EXAMPLE = ROOT / "settings.example.yaml"

pytestmark = [
    pytest.mark.skipif(shutil.which("helm") is None, reason="needs helm"),
    # The chart's dependencies are fetched over the network (helm dependency build), which
    # tests don't do. The charts job in CI and scripts/check.sh fetch them first.
    pytest.mark.skipif(
        not (CHART / "charts").is_dir(), reason="the chart's dependencies aren't fetched: helm dependency build chart/ok3d"
    ),
]
DEMO_DEVICES = ROOT / "devices.demo.yaml"


def helm(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["helm", *args], cwd=ROOT, capture_output=True, text=True, check=False)


def render(*extra: str) -> str:
    result = helm("template", "ok3d", str(CHART), "--namespace", "monitoring", "--values", str(EXAMPLE), *extra)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_the_chart_lints_with_the_example_settings() -> None:
    result = helm("lint", "--strict", str(CHART), "--values", str(EXAMPLE))
    assert result.returncode == 0, result.stdout + result.stderr


def documents(rendered: str, kind: str) -> list[str]:
    return [d for d in rendered.split("\n---\n") if f"\nkind: {kind}\n" in f"\n{d}\n"]


def test_every_namespace_enforces_the_restricted_standard() -> None:
    # monitoring, the release's own, is made by ok3d apply with the same labels.
    namespaces = documents(render(), "Namespace")
    assert len(namespaces) == 3
    assert not any("name: monitoring" in n for n in namespaces)
    for namespace in namespaces:
        assert "pod-security.kubernetes.io/enforce: restricted" in namespace


def test_every_check_of_every_device_is_a_probe_with_its_labels() -> None:
    rendered = render("--values", str(DEMO_DEVICES))
    probes = documents(rendered, "Probe")
    # router: ping and http; three switches and APs, the printer, and the controller: ping;
    # the NAS: ping and http.
    assert len(probes) == 9
    nas_http = next(p for p in probes if "name: device-nas-http" in p)
    assert '- "http://198.51.100.20/"' in nas_http and "module: http_2xx" in nas_http
    assert 'device: "nas"' in nas_http and 'behind: "office-switch"' in nas_http
    assert "ok3d-prometheus-blackbox-exporter.monitoring.svc:9115" in nas_http
    scrape = documents(rendered, "ScrapeConfig")
    assert len(scrape) == 1 and '- "198.51.100.50:9130"' in scrape[0]


def test_tcp_and_https_checks_and_metrics_paths(tmp_path: Path) -> None:
    devices = tmp_path / "devices.yaml"
    devices.write_text(
        "devices:\n  - name: server\n    address: 192.168.1.20\n    role: server\n"
        "    checks: [https, tcp:22]\n    metrics: [\"9100\", \"8080/probe/metrics\"]\n"
    )
    rendered = render("--values", str(devices))
    assert "module: https_2xx" in rendered and '- "https://192.168.1.20/"' in rendered
    assert "module: tcp_connect" in rendered and '- "192.168.1.20:22"' in rendered
    assert "metricsPath: /metrics" in rendered and "metricsPath: /probe/metrics" in rendered


def test_unifi_runs_unpoller_with_its_key_from_the_secret() -> None:
    rendered = render("--set", "modules.unifi=true", "--set", "unifi.url=https://192.168.1.1")
    unpoller = documents(rendered, "Deployment")
    unpoller = [d for d in unpoller if "name: unpoller" in d]
    assert len(unpoller) == 1
    assert "@sha256:" in unpoller[0]
    assert "name: ok3d-unifi" in unpoller[0] and "key: api-key" in unpoller[0]
    assert 'name: UP_UNIFI_DEFAULT_SAVE_DPI\n              value: "false"' in unpoller[0]


def test_unifi_on_without_an_address_is_refused() -> None:
    result = helm("template", "ok3d", str(CHART), "--values", str(EXAMPLE), "--set", "modules.unifi=true")
    assert result.returncode != 0
    assert "set unifi.url" in result.stderr


@pytest.mark.parametrize(
    ("device", "why"),
    [
        ("name: Router\n    address: 192.168.1.1\n    role: gateway", "a name with capitals"),
        ("name: router\n    address: 192.168.1.1\n    role: toaster", "a role that doesn't exist"),
        ("name: router\n    address: 192.168.1.1\n    role: gateway\n    checks: [smtp]", "a check that doesn't exist"),
        ("name: router\n    address: 192.168.1.1\n    role: gateway\n    checks: [tcp:0]", "port 0"),
        ("name: router\n    address: 192.168.1.1\n    role: gateway\n    colour: red", "an unknown field"),
        ("name: router\n    role: gateway", "no address"),
        ("name: router\n    address: 'a b'\n    role: gateway", "an address with a space"),
    ],
)
def test_the_schema_refuses_a_bad_device(tmp_path: Path, device: str, why: str) -> None:
    devices = tmp_path / "devices.yaml"
    devices.write_text(f"devices:\n  - {device}\n")
    result = helm("template", "ok3d", str(CHART), "--values", str(EXAMPLE), "--values", str(devices))
    assert result.returncode != 0, f"the schema accepted {why}"


def test_the_pages_certificate_covers_the_domain_and_every_name_under_it() -> None:
    rendered = render("--set", "tls.domain=noc.example.org")
    assert "kind: ClusterIssuer" in rendered
    assert '- "noc.example.org"' in rendered
    assert '- "*.noc.example.org"' in rendered


def test_the_cluster_settings_have_every_key_ok3d_reads() -> None:
    result = helm(
        "template", "ok3d", str(CHART), "--values", str(EXAMPLE), "--show-only", "templates/cluster-settings.yaml"
    )
    assert result.returncode == 0, result.stderr
    for key in ("CLUSTER_NAME", "K3S_IMAGE", "NETWORK", "API_PORT", "PUBLISH_ADDRESS", "HTTPS_PORT", "DATA_ROOT",
                "TLS_MODE", "DOMAIN", "METRICS_RETENTION", "METRICS_RETENTION_SIZE", "MODULE_UNIFI"):
        assert f"  {key}: " in result.stdout


@pytest.mark.parametrize(
    ("setting", "why"),
    [
        ("cluster.name=Bad_Name", "a cluster name with capitals or underscores"),
        ("cluster.k3sImage=rancher/k3s:latest", "an image tagged latest"),
        ("cluster.k3sImage=rancher/k3s:v1.36.4-k3s1", "Kubernetes older than 1.37"),
        ("cluster.apiPort=80", "an API port below 1024"),
        ("cluster.publishAddress=999.1.1.1", "an address that isn't one"),
        ("host.dataRoot=srv/ok3d", "a data root that isn't an absolute path"),
        ("host.dataRoot=/srv/my data", "a data root with a space"),
        ("tls.mode=public", "public certificates, which come in 1.1"),
        ("tls.domain=Bad_Domain", "a domain that isn't one"),
        ("modules.unifi=yes", "a switch that isn't true or false"),
        ("settingsVersion=2", "a settings layout this release can't read"),
        ("host.uid=0", "running as root"),
        ("metrics.retention=forever", "a retention that isn't a duration"),
        ("metrics.retentionSize=40", "a size with no unit"),
        ("unifi.url=ftp://192.168.1.1", "a controller address that isn't https"),
        ("nosuch=1", "a misspelled or unknown setting"),
        ("cluster.nosuch=1", "an unknown setting inside a section"),
    ],
)
def test_the_schema_refuses(setting: str, why: str) -> None:
    flag = "--set-string" if setting.startswith("modules.") else "--set"
    result = helm("template", "ok3d", str(CHART), "--values", str(EXAMPLE), flag, setting)
    assert result.returncode != 0, f"the schema accepted {setting} ({why})"


def _undescribed(node: dict[str, Any], path: str = "") -> list[str]:
    """Every setting under this schema node that has no description."""
    missing = []
    for name, child in node.get("properties", {}).items():
        here = f"{path}{name}"
        if not str(child.get("description", "")).strip():
            missing.append(here)
        missing += _undescribed(child, here + ".")
    return missing


def test_every_setting_is_described_and_the_schema_is_closed() -> None:
    # docs/settings.md is made from these descriptions, so a setting without one is a setting
    # nobody can look up. Every section refuses keys it doesn't list, so the schema can't fall
    # behind values.yaml without Helm refusing the defaults (test_the_chart_lints...).
    schema = json.loads((CHART / "values.schema.json").read_text())
    assert not _undescribed(schema), f"settings with no description: {_undescribed(schema)}"

    def closed(node: dict[str, Any], path: str = "settings") -> list[str]:
        open_sections = [] if node.get("additionalProperties") is False else [path]
        for name, child in node.get("properties", {}).items():
            if child.get("type") == "object" and "properties" in child:
                open_sections += closed(child, f"{path}.{name}")
        return open_sections

    assert not closed(schema), f"sections that accept unknown keys: {closed(schema)}"


def test_http_checks_accept_the_http_versions_home_devices_use() -> None:
    # Printers, NAS pages, and small switches often answer in HTTP/1.0, which blackbox
    # refuses unless it's listed. The demo's devices do too, which a real run caught.
    config = next(d for d in documents(render(), "ConfigMap") if "blackbox.yaml" in d)
    # Once for http_2xx and once for https_2xx.
    assert config.count("HTTP/1.0") == 2


def test_kubernetes_internal_metrics_stay_off() -> None:
    # k3s serves the API server's tens of thousands of series on the kubelet's endpoint too.
    # With them on, an empty cluster held about 100,000 series; with them off, about 5,000.
    rendered = render()
    monitors = documents(rendered, "ServiceMonitor")
    assert not any("apiserver" in m and "component: apiserver" in m for m in monitors)
    kubelet = next(m for m in monitors if "name: ok3d-kube-prometheus-stack-kubelet" in m)
    assert "/metrics/cadvisor" in kubelet
    assert "path: /metrics\n" not in kubelet and "path: /metrics/probes" not in kubelet


def test_ping_runs_without_root_or_extra_capabilities() -> None:
    rendered = render()
    blackbox = next(d for d in documents(rendered, "Deployment") if "blackbox-exporter" in d)
    assert "net.ipv4.ping_group_range" in blackbox
    assert "NET_RAW" not in blackbox
    assert "runAsNonRoot: true" in blackbox


def test_every_rule_file_becomes_a_prometheus_rule() -> None:
    rules = documents(render(), "PrometheusRule")
    ours = [r for r in rules if "app.kubernetes.io/part-of: ok3d" in r and "name: ok3d-" in r]
    files = sorted(p.stem for p in (CHART / "rules").glob("*.yaml"))
    assert sorted(r.split("name: ok3d-", 1)[1].split("\n", 1)[0] for r in ours) == files
    # The rules' own templates reach Prometheus as written.
    assert any("{{ $labels.device }}" in r for r in ours)


def test_alertmanager_keeps_its_state_in_the_data_root_and_reads_secrets_as_files() -> None:
    rendered = render()
    volumes = documents(rendered, "PersistentVolume")
    assert any("path: /var/lib/ok3d/alertmanager" in v and "ok3d/volume: alertmanager" in v for v in volumes)
    alertmanager = next(d for d in documents(rendered, "Alertmanager"))
    assert "configSecret: ok3d-alertmanager" in alertmanager
    assert "- ok3d-alerts" in alertmanager
    assert "disableMountSubPath: true" in alertmanager


@pytest.mark.parametrize(
    ("setting", "why"),
    [
        ("alerts.email.to=not-an-address", "an email address that isn't one"),
        ("alerts.repeatCritical=often", "a repeat that isn't a duration"),
        ("alerts.ntfy.server=ntfy.sh", "an ntfy server without https://"),
    ],
)
def test_the_schema_refuses_bad_alert_settings(setting: str, why: str) -> None:
    result = helm("template", "ok3d", str(CHART), "--values", str(EXAMPLE), "--set", setting)
    assert result.returncode != 0, f"the schema accepted {why}"


def test_email_on_needs_its_addresses() -> None:
    result = helm("template", "ok3d", str(CHART), "--values", str(EXAMPLE), "--set", "alerts.email.enabled=true")
    assert result.returncode != 0


def test_no_alert_fires_because_a_target_ok3d_turns_off_is_missing() -> None:
    # The kubelet's own endpoint and the API server aren't scraped (they're tens of thousands
    # of series), so an alert that fires when one of them is missing would fire forever: an
    # "unless ... up{job=...} == 1" or an absent(up{job=...}). A real run caught KubeletDown
    # pending this way. (Alerts on "up{job=...} == 0" are fine: with no target, there's no
    # series to be 0.)
    import re

    rules = "\n".join(documents(render(), "PrometheusRule"))
    unscraped = r'up\{job="(?:kubelet", ?metrics_path="/metrics"|apiserver|node-exporter|kube-scheduler|kube-proxy)'
    missing = re.compile(rf"(?:unless[^\n]*\n?[^\n]*{unscraped}[^}}]*\}} == 1|absent\({unscraped})")
    assert not missing.search(rules), f"an alert fires while a target ok3d doesn't scrape is missing: {missing.findall(rules)}"


CA_PEM = "-----BEGIN CERTIFICATE-----\nMIIBexample=\n-----END CERTIFICATE-----\n"


def gateway_config(tmp_path: Path, *extra: str) -> dict[str, Any]:
    import yaml

    rendered = render(*extra)
    config_map = next(d for d in documents(rendered, "ConfigMap") if "name: ok3d-gateway" in d)
    config: dict[str, Any] = yaml.safe_load(yaml.safe_load(config_map)["data"]["config.yaml"])
    return config


def routes(config: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = config["binds"][0]["listeners"][0]["routes"]
    return found


def test_the_gateway_serves_https_for_every_name_with_the_pages_certificate(tmp_path: Path) -> None:
    listener = gateway_config(tmp_path)["binds"][0]["listeners"][0]
    assert listener["protocol"] == "HTTPS" and listener["hostname"] == "*.noc.home.arpa"
    assert listener["tls"]["minTLSVersion"] == "TLS_V1_2"
    by_name = {r["name"]: r for r in routes(gateway_config(tmp_path))}
    # Prometheus and Alertmanager have no login of their own, so the gateway asks; Grafana has one.
    for page in ("prometheus", "alertmanager"):
        assert by_name[page]["policies"]["basicAuth"]["htpasswd"]["file"] == "/auth/htpasswd"
        assert by_name[page]["policies"]["localRateLimit"]
    assert "basicAuth" not in by_name["grafana"]["policies"]
    for route in by_name.values():
        if "backends" in route:
            assert route["policies"]["responseHeaderModifier"]["set"]["x-frame-options"] == "DENY"


def test_the_certificate_authority_is_served_only_once_ok3d_passes_it(tmp_path: Path) -> None:
    ca = tmp_path / "ca.crt"
    ca.write_text(CA_PEM)
    without = [r["name"] for r in routes(gateway_config(tmp_path))]
    assert "certificate-authority" not in without
    served = {r["name"]: r for r in routes(gateway_config(tmp_path, "--set-file", f"tls.caCertificate={ca}"))}
    response = served["certificate-authority"]["policies"]["directResponse"]
    assert "MIIBexample=" in response["bodyExpression"]
    assert response["headers"]["content-type"] == '"application/x-x509-ca-cert"'


def test_any_other_name_gets_a_404_from_the_last_route(tmp_path: Path) -> None:
    last = routes(gateway_config(tmp_path))[-1]
    assert last["name"] == "not-found" and "hostnames" not in last
    assert last["policies"]["directResponse"]["status"] == 404


def test_the_gateway_runs_hardened_with_its_password_only_from_the_secret() -> None:
    gateway = next(d for d in documents(render(), "Deployment") if "name: ok3d-gateway" in d)
    assert "runAsNonRoot: true" in gateway and "readOnlyRootFilesystem: true" in gateway
    assert gateway.count('drop: ["ALL"]') + gateway.count("- ALL") >= 2
    assert "@sha256:" in gateway
    assert "name: ok3d-admin" in gateway and "admin-password" in gateway
    service = next(d for d in documents(render(), "Service") if "name: ok3d-gateway\n" in d)
    assert "type: LoadBalancer" in service


def test_dashboards_have_their_datasources_and_dpi_stays_out() -> None:
    dashboards = [d for d in documents(render(), "ConfigMap") if 'grafana_dashboard: "1"' in d and "ok3d-dashboard-" in d]
    names = sorted(d.split("name: ok3d-dashboard-", 1)[1].split("\n", 1)[0] for d in dashboards)
    assert names == ["devices", "unifi-11311", "unifi-11312", "unifi-11313", "unifi-11314", "unifi-11315"]
    assert not any("${DS_" in d for d in dashboards)


def test_grafana_sends_nothing_anywhere_and_lets_no_one_sign_up() -> None:
    ini = next(d for d in documents(render(), "ConfigMap") if "grafana.ini:" in d)
    for setting in ("reporting_enabled = false", "check_for_updates = false", "allow_sign_up = false",
                    "cookie_secure = true"):
        assert setting in ini, setting


def test_every_ok3d_namespace_turns_away_what_it_doesnt_list() -> None:
    import yaml

    policies = [yaml.safe_load(d) for d in documents(render(), "NetworkPolicy")]
    deny = {p["metadata"]["namespace"] for p in policies
            if p["metadata"]["name"] == "ok3d-deny-by-default" and p["spec"] == {"podSelector": {}, "policyTypes": ["Ingress"]}}
    assert deny == {"monitoring", "gateway", "auth", "agents"}


def test_the_gateway_reaches_only_the_pages_web_ports() -> None:
    import yaml

    policies = {p["metadata"]["name"]: p for p in (yaml.safe_load(d) for d in documents(render(), "NetworkPolicy"))}
    pages = policies["ok3d-pages-from-the-gateway"]["spec"]
    assert sorted(pages["podSelector"]["matchExpressions"][0]["values"]) == ["alertmanager", "grafana", "prometheus"]
    rule = pages["ingress"][0]
    assert rule["from"][0]["podSelector"] == {"matchLabels": {"app.kubernetes.io/name": "ok3d-gateway"}}
    assert sorted(port["port"] for port in rule["ports"]) == [3000, 9090, 9093]
    gateway = policies["ok3d-gateway"]["spec"]["ingress"]
    assert [port["port"] for rule in gateway for port in rule["ports"]] == [8443, 15020]
    # Its metrics are for monitoring only.
    assert gateway[1]["from"][0]["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"] == "monitoring"


def test_validate_refuses_settings_the_schema_refuses(tmp_path: Path) -> None:
    # ./ok3d validate, with the real Helm and schema: what the helper runs before it saves a
    # file the Dashboard sent.
    good = tmp_path / "good.yaml"
    good.write_text(EXAMPLE.read_text())
    bad = tmp_path / "bad.yaml"
    bad.write_text(EXAMPLE.read_text() + "\ncluster:\n  ports:\n    https: lots\n")
    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(ROOT / "ok3d"), *args], cwd=ROOT, capture_output=True, text=True, check=False)

    assert run("validate", "settings", str(good)).returncode == 0
    refused = run("validate", "settings", str(bad))
    assert refused.returncode != 0
    assert "aren't valid" in refused.stderr


def test_validate_refuses_devices_the_schema_refuses(tmp_path: Path) -> None:
    bad = tmp_path / "devices.yaml"
    bad.write_text("devices:\n  - name: x\n    address: 192.0.2.1\n    role: toaster\n")
    env = {**os.environ, "OK3D_SETTINGS": str(EXAMPLE)}
    result = subprocess.run([str(ROOT / "ok3d"), "validate", "devices", str(bad)], cwd=ROOT,
                            capture_output=True, text=True, check=False, env=env)  # fmt: skip
    assert result.returncode == 1
    assert "FAIL  the devices in" in result.stdout
