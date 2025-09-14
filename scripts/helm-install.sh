#!/usr/bin/env bash
set -euo pipefail

NS=monitoring

kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f monitoring/storage.yaml

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

helm upgrade --install kube-prometheus prometheus-community/kube-prometheus-stack \
  -n "$NS" \
  -f monitoring/helm/kube-prometheus-stack-values.yaml

kubectl wait --for=condition=Established crd/prometheusrules.monitoring.coreos.com --timeout=180s || true
kubectl wait --for=condition=Established crd/servicemonitors.monitoring.coreos.com --timeout=180s || true
kubectl wait --for=condition=Established crd/probes.monitoring.coreos.com --timeout=180s || true
kubectl wait --for=condition=Established crd/alertmanagers.monitoring.coreos.com --timeout=180s || true

helm upgrade --install loki grafana/loki-stack \
  -n "$NS" \
  -f monitoring/loki-stack-values.yaml

helm upgrade --install blackbox prometheus-community/prometheus-blackbox-exporter \
  -n "$NS"

echo "Done. Next: kubectl apply -k monitoring/"
