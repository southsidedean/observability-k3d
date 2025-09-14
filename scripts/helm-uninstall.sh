#!/usr/bin/env bash
set -euo pipefail

NS=monitoring

helm uninstall kube-prometheus -n "$NS" || true
helm uninstall loki -n "$NS" || true
helm uninstall blackbox -n "$NS" || true

echo "Helm releases removed."
