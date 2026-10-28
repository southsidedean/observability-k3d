"""The alert rules: valid, tested, and watching metrics that really exist.

The old stack's UniFi rules watched unifi_device_* metrics, which unpoller never served, so
they could never fire, and nothing noticed. Here every metric a rule uses must appear in what
its exporter really serves: the names recorded in tests/fixtures/ (node_exporter, blackbox)
and the ones the vendored UniFi dashboards query (unpoller). When an exporter renames a
metric, the version bump that brings it fails here.

promtool's own checks and unit tests (tests/rules/) run when promtool is installed; CI
installs it. Every alert also needs a severity, a summary, and a runbook that exists.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
RULES = sorted((ROOT / "chart" / "ok3d" / "rules").glob("*.yaml"))
FIXTURES = ROOT / "tests" / "fixtures"
DASHBOARDS = ROOT / "chart" / "ok3d" / "dashboards"

# Prometheus's own series: up is written for every scrape target.
BUILT_IN = {"up"}
KEYWORDS = {"and", "or", "unless", "by", "without", "on", "ignoring", "group_left", "group_right", "bool", "offset"}


def rules() -> list[dict[str, Any]]:
    found = []
    for path in RULES:
        for group in yaml.safe_load(path.read_text())["groups"]:
            found += [{**rule, "file": path.name} for rule in group["rules"]]
    return found


def known_metrics() -> set[str]:
    names = set(BUILT_IN)
    for fixture in FIXTURES.glob("*.metrics"):
        names |= {line.strip() for line in fixture.read_text().splitlines() if line.strip()}
    for dashboard in DASHBOARDS.glob("unifi-*.json"):
        names |= set(re.findall(r"\bunpoller_[a-z_]+", dashboard.read_text()))
    return names


def metrics_in(expr: str) -> set[str]:
    """The metric names a PromQL expression reads: its identifiers, without functions,
    keywords, label matchers, strings, durations, or the labels in by (...) and the like."""
    text = re.sub(r'"(?:[^"\\]|\\.)*"', "", expr)  # strings
    text = re.sub(r"\{[^}]*\}", "", text)  # label matchers
    text = re.sub(r"\[[^\]]*\]", "", text)  # ranges and subqueries
    text = re.sub(r"\b(by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)", "", text)
    names = set()
    for match in re.finditer(r"[A-Za-z_:][A-Za-z0-9_:]*", text):
        name = match.group(0)
        if name in KEYWORDS or text[match.end():].lstrip().startswith("("):
            continue  # a keyword, or a function such as rate( or time(
        names.add(name)
    return names


def test_there_are_rules_to_check() -> None:
    assert len(rules()) >= 12


@pytest.mark.parametrize("rule", rules(), ids=lambda rule: rule["alert"])
def test_every_metric_a_rule_uses_really_exists(rule: dict[str, Any]) -> None:
    unknown = metrics_in(rule["expr"]) - known_metrics()
    assert not unknown, f"{rule['alert']} ({rule['file']}) uses metrics no exporter serves: {unknown}"


@pytest.mark.parametrize("rule", rules(), ids=lambda rule: rule["alert"])
def test_every_alert_has_a_severity_a_summary_and_a_runbook(rule: dict[str, Any]) -> None:
    assert rule["labels"]["severity"] in {"critical", "warning", "info"}
    assert rule["annotations"]["summary"].strip()
    runbook = rule["annotations"]["runbook_url"]
    prefix = "https://github.com/southsidedean/observability-k3d/blob/main/"
    assert runbook == f"{prefix}docs/runbooks/{rule['alert']}.md"
    assert (ROOT / runbook.removeprefix(prefix)).is_file(), f"no runbook at {runbook.removeprefix(prefix)}"


def test_every_rule_file_has_its_promtool_tests() -> None:
    for path in RULES:
        assert (ROOT / "tests" / "rules" / f"{path.stem}.test.yaml").is_file(), f"{path.name} has no tests"


def test_every_alert_is_tested() -> None:
    tested = set()
    for test_file in (ROOT / "tests" / "rules").glob("*.test.yaml"):
        for test in yaml.safe_load(test_file.read_text())["tests"]:
            tested |= {case["alertname"] for case in test.get("alert_rule_test", []) if case.get("exp_alerts")}
    untested = {rule["alert"] for rule in rules()} - tested
    assert not untested, f"alerts no promtool test sees firing: {untested}"


def test_the_metric_finder_finds_what_it_should() -> None:
    assert metrics_in('probe_success{job="devices", check="ping"} == 0') == {"probe_success"}
    assert metrics_in("(probe_ssl_earliest_cert_expiry - time()) < 14 * 86400") == {"probe_ssl_earliest_cert_expiry"}
    assert metrics_in("changes(probe_success[15m]) >= 4") == {"probe_success"}
    assert metrics_in("sum by (device) (rate(node_cpu_seconds_total[5m]))") == {"node_cpu_seconds_total"}
    assert metrics_in("a / on (instance) group_left (name) b") == {"a", "b"}


promtool = shutil.which("promtool") or (str(ROOT / ".venv" / "bin" / "promtool") if (ROOT / ".venv" / "bin" / "promtool").is_file() else None)


@pytest.mark.skipif(promtool is None, reason="needs promtool (CI installs it)")
def test_promtool_checks_the_rules_and_runs_their_tests() -> None:
    assert promtool is not None
    check = subprocess.run([promtool, "check", "rules", *map(str, RULES)], capture_output=True, text=True, check=False)
    assert check.returncode == 0, check.stdout + check.stderr
    tests = sorted(map(str, (ROOT / "tests" / "rules").glob("*.test.yaml")))
    run = subprocess.run([promtool, "test", "rules", *tests], capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stdout + run.stderr


def test_the_old_stacks_unifi_rules_would_have_been_caught() -> None:
    # The rules v0.2.0 shipped, which never fired because unpoller doesn't serve these names.
    for expr in ('unifi_device_state{state="0"} == 1', "unifi_device_cpu > 85", "unifi_device_mem > 85"):
        assert metrics_in(expr) - known_metrics(), f"the check would have let {expr!r} through"
