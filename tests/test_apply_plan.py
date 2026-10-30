"""Tests for src/ok3d/apply_plan.py: what Apply would restart, stop, or start, from the release
as it's deployed and a server-side dry run of what Apply would deploy."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ok3d import apply_plan

ROOT = Path(__file__).resolve().parent.parent


def obj(kind: str, name: str, body: str = "spec: {}", namespace: str = "monitoring") -> str:
    return f"# Source: x.yaml\napiVersion: v1\nkind: {kind}\nmetadata:\n  name: {name}\n  namespace: {namespace}\n{body}\n"


def manifest(*docs: str) -> str:
    return "---\n" + "---\n".join(docs)


GRAFANA = obj("Deployment", "ok3d-grafana", "spec:\n  replicas: 1")
RULES = obj("PrometheusRule", "ok3d-rules", "spec:\n  groups: []")


def test_nothing_changed() -> None:
    plan = apply_plan.compare(manifest(GRAFANA, RULES), manifest(GRAFANA, RULES))
    assert plan.lines() == "state=none\nother=0\n"


def test_a_changed_workload_restarts_and_other_changes_are_counted() -> None:
    after = manifest(obj("Deployment", "ok3d-grafana", "spec:\n  replicas: 2"), obj("PrometheusRule", "ok3d-rules", "spec:\n  groups: [x]"))
    assert apply_plan.compare(manifest(GRAFANA, RULES), after).lines() == "state=changes\nrestart=Grafana\nother=1\n"


def test_a_workload_gone_stops_and_a_new_one_starts() -> None:
    unpoller = obj("Deployment", "unpoller")
    prometheus = obj("Prometheus", "ok3d-kube-prometheus-stack-prometheus")
    plan = apply_plan.compare(manifest(GRAFANA, unpoller), manifest(GRAFANA, prometheus))
    assert plan.stop == ["the UniFi exporter (unpoller)"] and plan.start == ["Prometheus"]


def test_a_workload_without_a_plain_name_is_shown_by_kind_and_name() -> None:
    plan = apply_plan.compare(manifest(), manifest(obj("StatefulSet", "something-new")))
    assert plan.start == ["StatefulSet/something-new"]


def test_a_name_in_the_spec_isnt_taken_for_the_objects() -> None:
    doc = "apiVersion: v1\nkind: Deployment\nspec:\n  name: decoy\nmetadata:\n  name: ok3d-grafana\n"
    assert list(apply_plan.objects(manifest(doc))) == [("Deployment", "", "ok3d-grafana")]


def test_the_same_name_in_another_namespace_is_another_object() -> None:
    a, b = obj("Deployment", "x", namespace="monitoring"), obj("Deployment", "x", namespace="gateway")
    assert len(apply_plan.objects(manifest(a, b))) == 2


def test_the_manifest_is_taken_from_the_dry_runs_output() -> None:
    out = f"NAME: ok3d\nHOOKS:\n---\n{obj('Job', 'hook')}MANIFEST:\n{manifest(GRAFANA)}\nNOTES:\nsome notes\n"
    after = apply_plan.manifest_of(out)
    assert after is not None and "ok3d-grafana" in after and "hook" not in after and "some notes" not in after
    assert apply_plan.manifest_of("Error: nothing") is None


def run(tmp_path: Path, now: str, dry_run: str) -> str:
    (tmp_path / "now").write_text(now)
    (tmp_path / "next").write_text(dry_run)
    return subprocess.run([sys.executable, "-I", str(ROOT / "src" / "ok3d" / "apply_plan.py"), str(tmp_path / "now"),
                           str(tmp_path / "next")], capture_output=True, text=True, check=True).stdout  # fmt: skip


def test_it_runs_isolated_and_prints_the_lines(tmp_path: Path) -> None:
    out = run(tmp_path, manifest(GRAFANA), f"MANIFEST:\n{manifest(obj('Deployment', 'ok3d-grafana', 'spec:\n  replicas: 3'))}")
    assert out == "state=changes\nrestart=Grafana\nother=0\n"


def test_it_cant_tell_without_both_manifests(tmp_path: Path) -> None:
    assert run(tmp_path, manifest(GRAFANA), "Error: the dry run failed") == "state=unknown\n"
    assert run(tmp_path, "", f"MANIFEST:\n{manifest(GRAFANA)}") == "state=unknown\n"
