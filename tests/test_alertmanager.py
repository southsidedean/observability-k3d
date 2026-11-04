"""Alertmanager's settings, rendered from alerts.* by the chart and checked with Alertmanager's
own amtool: they load, and each kind of alert goes where it should. Skipped without helm, the
chart's dependencies, or amtool; CI has all three.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CHART = ROOT / "chart" / "ok3d"
LOCAL_AMTOOL = ROOT / ".venv" / "bin" / "amtool"
amtool = shutil.which("amtool") or (str(LOCAL_AMTOOL) if LOCAL_AMTOOL.is_file() else None)

pytestmark = [
    pytest.mark.skipif(shutil.which("helm") is None, reason="needs helm"),
    pytest.mark.skipif(not (CHART / "charts").is_dir(), reason="the chart's dependencies aren't fetched"),
    pytest.mark.skipif(amtool is None, reason="needs amtool (CI installs it)"),
]

EVERYTHING_ON = [
    "alerts.ntfy.enabled=true", "alerts.ntfy.useToken=true", "alerts.deadman.enabled=true",
    "alerts.email.enabled=true", "alerts.email.to=you@example.com", "alerts.email.from=noc@example.com",
    "alerts.email.smarthost=smtp.example.com:587", "alerts.email.username=noc@example.com",
]


def config(tmp_path: Path, *settings: str) -> Path:
    """Alertmanager's settings as the chart renders them, written to a file amtool can read."""
    args = ["helm", "template", "ok3d", str(CHART), "--values", str(ROOT / "settings.example.yaml"),
            "--show-only", "templates/alertmanager-config.yaml"]
    for setting in settings:
        args += ["--set", setting]
    rendered = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    path = tmp_path / "alertmanager.yaml"
    path.write_text(yaml.safe_load(rendered)["stringData"]["alertmanager.yaml"])
    return path


def receiver(path: Path, *labels: str) -> str:
    assert amtool is not None
    result = subprocess.run([amtool, "config", "routes", "test", f"--config.file={path}", *labels],
                            capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.mark.parametrize("settings", [[], EVERYTHING_ON], ids=["nothing on", "everything on"])
def test_the_settings_load(tmp_path: Path, settings: list[str]) -> None:
    assert amtool is not None
    path = config(tmp_path, *settings)
    result = subprocess.run([amtool, "check-config", str(path)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_each_kind_of_alert_goes_where_it_should(tmp_path: Path) -> None:
    path = config(tmp_path, *EVERYTHING_ON)
    assert receiver(path, "alertname=DeviceDown", "severity=critical", "device=printer") == "you"
    assert receiver(path, "alertname=DeviceCheckFailing", "severity=warning", "device=nas") == "you"
    # The always-firing Watchdog keeps the dead man's switch fed; info alerts stay quiet.
    assert receiver(path, "alertname=Watchdog", "severity=none") == "deadman"
    assert receiver(path, "alertname=InfoInhibitor", "severity=none") == "nobody"
    assert receiver(path, "alertname=KubeletTooManyPods", "severity=info") == "nobody"


def test_the_watchdog_is_routed_first_every_minute_and_stops_there(tmp_path: Path) -> None:
    # First and without continue, so no later route (critical alerts to you, say) can take it
    # or send it on to you as well.
    routes = yaml.safe_load(config(tmp_path, *EVERYTHING_ON).read_text())["route"]["routes"]
    assert routes[0]["matchers"] == ['alertname = "Watchdog"']
    assert not routes[0].get("continue", False)
    # A repeat is sent at a group_interval tick once repeat_interval has passed. Equal, the tick
    # lands a moment short and the repeat waits for the next: every 2 minutes, as the test VM
    # showed. Just under it, every tick sends.
    assert routes[0]["group_interval"] == "1m" and routes[0]["repeat_interval"] == "50s"


def test_critical_and_warning_alerts_repeat_at_their_own_pace(tmp_path: Path) -> None:
    settings = yaml.safe_load(config(tmp_path, "alerts.repeatCritical=2h", "alerts.repeatWarning=24h").read_text())
    assert settings["route"]["repeat_interval"] == "24h"  # warnings, and anything else to you
    critical = next(r for r in settings["route"]["routes"] if r["matchers"] == ['severity = "critical"'])
    assert critical["receiver"] == "you" and critical["repeat_interval"] == "2h"


def test_an_emails_subject_names_the_cluster_and_whether_it_cleared(tmp_path: Path) -> None:
    settings = yaml.safe_load(config(tmp_path, *EVERYTHING_ON, "cluster.name=noc2").read_text())
    you = next(r for r in settings["receivers"] if r["name"] == "you")
    subject = you["email_configs"][0]["headers"]["Subject"]
    assert subject.startswith("[noc2] ")
    assert '{{ if eq .Status "resolved" }}Cleared: {{ end }}' in subject
    assert "{{ .CommonLabels.alertname }}" in subject and ".CommonAnnotations.summary" in subject


def test_without_a_dead_mans_switch_the_watchdog_goes_nowhere(tmp_path: Path) -> None:
    assert receiver(config(tmp_path), "alertname=Watchdog", "severity=none") == "nobody"


def test_secrets_are_files_never_values(tmp_path: Path) -> None:
    settings = yaml.safe_load(config(tmp_path, *EVERYTHING_ON).read_text())
    assert settings["global"]["smtp_auth_password_file"].startswith("/etc/alertmanager/secrets/ok3d-alerts/")
    assert "smtp_auth_password" not in settings["global"]
    hooks = [hook for r in settings["receivers"] for hook in r.get("webhook_configs", [])]
    assert hooks and all("url_file" in hook and "url" not in hook for hook in hooks)


def test_a_device_being_down_holds_back_its_warnings_and_nothing_else(tmp_path: Path) -> None:
    # amtool can't test inhibition, so this checks the rule itself. Alertmanager counts a
    # label missing from both alerts as equal, so without the device matchers a critical alert
    # with no device would hold back every warning with none (UniFi's, Kubernetes' own).
    rules = yaml.safe_load(config(tmp_path).read_text())["inhibit_rules"]
    assert rules == [{"source_matchers": ['severity = "critical"', 'device =~ ".+"'],
                      "target_matchers": ['severity = "warning"', 'device =~ ".+"'],
                      "equal": ["device"]}]
