#!/usr/bin/env bash
set -euo pipefail

# Namespace
kubectl apply -f manifests/monitoring/unifi/namespace.yaml

# Patch local-path-provisioner to use host directory
echo "Patching local-path-provisioner to use /media/content/observability-k3d/local-path-storage ..."
kubectl apply -f manifests/storage/local-path-config-patch.yaml

# Add helm repos
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add grafana-loki https://grafana.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update

# Deploy Prometheus stack
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  -f manifests/monitoring/prometheus-values.yaml

# Deploy Loki+Promtail
helm upgrade --install loki-stack grafana/loki-stack \
  --namespace monitoring \
  -f manifests/monitoring/loki-stack-values.yaml

# Deploy Grafana (standalone, since kube-prom-stack grafana is disabled)
helm upgrade --install grafana grafana/grafana \
  --namespace monitoring \
  -f manifests/grafana-values.yaml

# Vendor dashboards (fetch JSONs) then kustomize apply to create ConfigMaps
scripts/vendor-unifi-dashboards.sh

# Unpoller resources + dashboard configmaps
kubectl apply -k manifests/monitoring

# kgateway routes
kubectl apply -f manifests/gateway/monitoring-httproutes.yaml

echo "Done. Visit http://localhost:7001/grafana (admin/admin)"
