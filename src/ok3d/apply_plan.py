"""What Apply would change in a running cluster: which parts it would restart, stop, or start.

`./ok3d check` runs this with two files: the ok3d release's manifest as it's deployed now
(`helm get manifest`), and what Apply would deploy, from a server-side dry run with Apply's
own arguments (`helm upgrade --dry-run=server`). It compares them one object at a time and
prints the answer as lines for the helper's folder, where the Dashboard reads it:

    state=changes
    restart=Grafana
    stop=the UniFi exporter (unpoller)
    other=3

A workload (a Deployment, StatefulSet, or DaemonSet, or the Prometheus and Alertmanager the
operator runs) is restarted when what Kubernetes rolls on changes: a Deployment's,
StatefulSet's, or DaemonSet's pod template or replica count, or the operator's spec. A change
elsewhere in it, such as the chart's label every release changes, restarts nothing, so it's
counted with the rest. One that's gone is stopped; a new one is started. Everything else (alert rules, dashboards, device checks) changes without stopping
anything, so it's only counted. state is none when nothing would change.

It uses only the standard library, and runs on the host's own Python (`python3 -I`).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# The kinds that run something: a change restarts it, and removing one stops it.
WORKLOADS = ("Deployment", "StatefulSet", "DaemonSet", "Prometheus", "Alertmanager")
# The ones the Prometheus operator runs: it rolls their pods when their spec changes.
OPERATED = ("Prometheus", "Alertmanager")
# Plain names for ok3d's workloads, by object name. Any other is shown as kind/name.
NAMES = {
    "ok3d-grafana": "Grafana",
    "ok3d-kube-prometheus-stack-prometheus": "Prometheus",
    "ok3d-kube-prometheus-stack-alertmanager": "Alertmanager",
    "ok3d-kube-prometheus-stack-operator": "the Prometheus operator",
    "ok3d-kube-state-metrics": "kube-state-metrics",
    "ok3d-prometheus-blackbox-exporter": "the device checks (blackbox exporter)",
    "ok3d-gateway": "the gateway, which serves ok3d's pages",
    "unpoller": "the UniFi exporter (unpoller)",
}
# The most of either file that's read: a whole release is a few hundred KB.
MAX_READ = 16 * 1024 * 1024

KIND = re.compile(r"^kind: *(\S+)", re.MULTILINE)
# The name and namespace under metadata, not a name further down in the spec.
METADATA = re.compile(r"^metadata:\n((?:[ #].*\n?)*)", re.MULTILINE)
FIELD = r"^  {}: *['\"]?([^'\"\s]+)"
# The spec, and in it the pod template and the replica count, the way the charts write them.
SPEC = re.compile(r"^spec:\n((?:[ #].*\n?)*)", re.MULTILINE)
TEMPLATE = re.compile(r"^  template:\n(?:(?:    |\s*#).*\n?)*", re.MULTILINE)
REPLICAS = re.compile(r"^  replicas:.*$", re.MULTILINE)


@dataclass
class Plan:
    restart: list[str] = field(default_factory=list)
    stop: list[str] = field(default_factory=list)
    start: list[str] = field(default_factory=list)
    other: int = 0

    def lines(self) -> str:
        changed = self.restart or self.stop or self.start or self.other
        out = [f"state={'changes' if changed else 'none'}"]
        out += [f"restart={n}" for n in self.restart] + [f"stop={n}" for n in self.stop]
        out += [f"start={n}" for n in self.start] + [f"other={self.other}"]
        return "\n".join(out) + "\n"


class Unreadable(Exception):
    """An object whose kind this can read, but not its name: comparing without it could say
    nothing changes when something does."""


def objects(manifest: str) -> dict[tuple[str, str, str], str]:
    """Each object in a manifest, by (kind, namespace, name), as its text. Raises Unreadable
    for an object with a kind but no name this can find."""
    found = {}
    for doc in re.split(r"^---[ \t]*$", manifest, flags=re.MULTILINE):
        kind = KIND.search(doc)
        if not kind:
            continue  # only comments, or nothing
        metadata = METADATA.search(doc)
        name = metadata and re.search(FIELD.format("name"), metadata.group(1), re.MULTILINE)
        if not metadata or not name:
            raise Unreadable(kind.group(1))
        namespace = re.search(FIELD.format("namespace"), metadata.group(1), re.MULTILINE)
        found[(kind.group(1), namespace.group(1) if namespace else "", name.group(1))] = doc.strip()
    return found


def manifest_of(dry_run: str) -> str | None:
    """The manifest in `helm upgrade --dry-run` output: after MANIFEST:, up to NOTES: if
    there is one. None when there's no manifest at all."""
    found = re.search(r"^MANIFEST:\n", dry_run, re.MULTILINE)
    if found is None:
        return None
    return re.split(r"^NOTES:$", dry_run[found.end() :], maxsplit=1, flags=re.MULTILINE)[0]


def plain(key: tuple[str, str, str]) -> str:
    kind, _, name = key
    return NAMES.get(name, f"{kind}/{name}")


def runs(kind: str, doc: str) -> str:
    """The part of a workload that restarts it when it changes. When this can't find it, the
    whole object: better to ask first for nothing than to miss a restart."""
    spec = SPEC.search(doc)
    if spec is None:
        return doc
    if kind in OPERATED:
        return spec.group(1)
    template = TEMPLATE.search(spec.group(1))
    if template is None:
        return doc
    replicas = REPLICAS.search(spec.group(1))
    return template.group(0) + (replicas.group(0) if replicas else "")


def compare(now: str, after: str) -> Plan:
    before, next_ = objects(now), objects(after)
    plan = Plan()
    for key in sorted(set(before) | set(next_)):
        if before.get(key) == next_.get(key):
            continue
        if key[0] not in WORKLOADS:
            plan.other += 1
        elif key not in next_:
            plan.stop.append(plain(key))
        elif key not in before:
            plan.start.append(plain(key))
        elif runs(key[0], before[key]) == runs(key[0], next_[key]):
            plan.other += 1  # a label, say: nothing restarts
        else:
            plan.restart.append(plain(key))
    return plan


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: apply_plan.py DEPLOYED_MANIFEST DRY_RUN_OUTPUT", file=sys.stderr)
        return 2
    now, dry_run = (Path(a).read_bytes()[:MAX_READ].decode("utf-8", errors="replace") for a in argv)
    after = manifest_of(dry_run)
    try:
        if after is None or not objects(now):
            print("state=unknown")
            return 0
        print(compare(now, after).lines(), end="")
    except Unreadable:
        print("state=unknown")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
