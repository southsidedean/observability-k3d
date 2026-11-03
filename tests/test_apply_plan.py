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



def test_an_object_it_cant_read_makes_the_answer_unknown(tmp_path: Path) -> None:
    # A Deployment whose name isn't where it's looked for: comparing without it would say
    # nothing changes while its replicas do.
    odd = "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n    name: ok3d-grafana\nspec:\n  replicas: {}\n"
    before, after = manifest(RULES, odd.format(1)), manifest(RULES, odd.format(2))
    assert run(tmp_path, before, f"MANIFEST:\n{after}") == "state=unknown\n"


def gateway(chart: str = "ok3d-0.5.1", checksum: str = "abc", replicas: int = 1) -> str:
    # Shaped like the chart's gateway: the chart's label on the Deployment itself, and the
    # checksums on its pod template.
    return (
        "# Source: ok3d/templates/gateway.yaml\napiVersion: apps/v1\nkind: Deployment\nmetadata:\n"
        f"  name: ok3d-gateway\n  namespace: gateway\n  labels:\n    helm.sh/chart: \"{chart}\"\n"
        f"spec:\n  replicas: {replicas}\n  selector:\n    matchLabels:\n      app.kubernetes.io/name: ok3d-gateway\n"
        "  template:\n    metadata:\n      labels:\n        app.kubernetes.io/name: ok3d-gateway\n"
        f"      annotations:\n        checksum/admin: \"{checksum}\"\n    spec:\n      containers: []\n"
    )


def test_a_label_on_the_workload_itself_restarts_nothing() -> None:
    # A new release changes the chart's label on the Deployment, not its pod template:
    # Kubernetes restarts nothing, as the test VM showed, so Apply has nothing to ask about.
    plan = apply_plan.compare(manifest(gateway("ok3d-0.5.1")), manifest(gateway("ok3d-0.5.2")))
    assert plan.lines() == "state=changes\nother=1\n"


def test_a_changed_pod_template_restarts() -> None:
    plan = apply_plan.compare(manifest(gateway(checksum="abc")), manifest(gateway(checksum="def")))
    assert plan.restart == ["the gateway, which serves ok3d's pages"]


def test_a_changed_replica_count_is_shown_as_a_restart() -> None:
    plan = apply_plan.compare(manifest(gateway(replicas=1)), manifest(gateway(replicas=0)))
    assert plan.restart == ["the gateway, which serves ok3d's pages"]


def test_prometheus_restarts_on_its_spec_not_its_labels() -> None:
    def prometheus(label: str, retention: str) -> str:
        return obj("Prometheus", "ok3d-kube-prometheus-stack-prometheus",
                   f"spec:\n  retention: {retention}").replace("metadata:\n", f"metadata:\n  labels:\n    chart: {label}\n")
    assert apply_plan.compare(manifest(prometheus("a", "30d")), manifest(prometheus("b", "30d"))).restart == []
    assert apply_plan.compare(manifest(prometheus("a", "30d")), manifest(prometheus("a", "60d"))).restart == ["Prometheus"]


def test_a_workload_whose_pod_template_it_cant_find_restarts() -> None:
    # Better to ask first for nothing than to say nothing restarts when something does.
    before = obj("Deployment", "ok3d-grafana", "spec:\n  replicas: 1").replace("metadata:\n", "metadata:\n  labels: {a: b}\n")
    plan = apply_plan.compare(manifest(GRAFANA), manifest(before))
    assert plan.restart == ["Grafana"]


def test_a_change_after_a_blank_line_in_the_template_restarts() -> None:
    # Helm keeps a block scalar's blank lines (a script in args: |, say): the template goes on
    # after them, and so does the spec.
    def with_script(image: str) -> str:
        return gateway().replace("      containers: []\n",
                                 f"      containers:\n        - args: |\n            one\n\n            two\n          image: {image}\n")
    assert apply_plan.compare(manifest(with_script("a:1")), manifest(with_script("a:2"))).restart == [
        "the gateway, which serves ok3d's pages"]


def test_a_change_after_a_blank_line_in_prometheus_spec_restarts() -> None:
    def prometheus(replicas: int) -> str:
        return obj("Prometheus", "ok3d-kube-prometheus-stack-prometheus",
                   f"spec:\n  additionalArgs: |\n    a\n\n    b\n  replicas: {replicas}")
    assert apply_plan.compare(manifest(prometheus(1)), manifest(prometheus(2))).restart == ["Prometheus"]


def test_a_template_indented_another_way_restarts_on_any_change() -> None:
    # Valid YAML, but not the way the charts write it: the whole object is compared instead.
    def odd(image: str) -> str:
        return gateway().replace("  template:\n    metadata:", f"  template:\n   image: {image}\n   metadata:")
    assert apply_plan.compare(manifest(odd("a:1")), manifest(odd("a:2"))).restart == [
        "the gateway, which serves ok3d's pages"]
