"""The charts, rendered by the real Helm: they lint and render with the example settings, every
setting is described, the schema refuses what can't work, and what they render keeps ok3d's
rules (restricted namespaces, the certificate for every page). Skipped where Helm isn't
installed; CI installs it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHART = ROOT / "chart" / "ok3d"
EXAMPLE = ROOT / "settings.example.yaml"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="needs helm")


def helm(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["helm", *args], cwd=ROOT, capture_output=True, text=True, check=False)


def render(*extra: str) -> str:
    result = helm("template", "ok3d", str(CHART), "--namespace", "ok3d-system", "--values", str(EXAMPLE), *extra)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_the_chart_lints_with_the_example_settings() -> None:
    result = helm("lint", "--strict", str(CHART), "--values", str(EXAMPLE))
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_namespace_enforces_the_restricted_standard() -> None:
    documents = render().split("\n---\n")
    namespaces = [d for d in documents if "\nkind: Namespace\n" in f"\n{d}\n"]
    assert len(namespaces) == 4
    for namespace in namespaces:
        assert "pod-security.kubernetes.io/enforce: restricted" in namespace


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
                "TLS_MODE", "DOMAIN"):
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
