#!/bin/bash
# cluster-setup-k3d-observability-everything.sh
# Automates the creation of a k3d cluster with a full observability stack.
# Tom Dean
# Last edit: 9/12/2025

# --- Helper Functions ---
#set -euo pipefail

check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo "Error: '$1' command not found. Please install it and ensure it's in your PATH."
        exit 1
    fi
}

# --- Prerequisite Checks ---
echo "--- [1/7] Checking prerequisites..."
check_command k3d
check_command helm
check_command kubectl
check_command kubectx
check_command curl
echo "All prerequisites found."
echo

# Set environment variables
source vars.sh

# --- Cluster Setup ---
echo "--- [2/7] Setting up k3d cluster: $CLUSTER_NAME..."
echo "Deleting existing cluster (if any)..."
k3d cluster delete $CLUSTER_NAME

echo "Creating new k3d cluster..."
k3d cluster create $CLUSTER_NAME \
    -c cluster-k3d/k3d-cluster.yaml \
    --port 7001:80@loadbalancer \
    --port 7401:443@loadbalancer \
    --port "$SYSLOG_PORT_TCP:$SYSLOG_PORT_TCP/tcp@loadbalancer" \
    --port "$SYSLOG_PORT_UDP:$SYSLOG_PORT_UDP/udp@loadbalancer" \
    --volume "$PERSISTENT_DATA_PATH:$PERSISTENT_DATA_PATH@all" \
    --api-port 0.0.0.0:7601
k3d cluster list
echo

echo "Configuring kubectl context..."
kubectx -d $KUBECTX_NAME
kubectx $KUBECTX_NAME=k3d-$CLUSTER_NAME
kubectx $KUBECTX_NAME
kubectx
echo

# --- Core Components & CRDs ---
echo "--- [3/7] Installing Core Components (Gateway API, kagent, kgateway)..."
echo "Installing Gateway API CRDs..."
kubectl apply -f "https://github.com/kubernetes-sigs/gateway-api/releases/download/${GATEWAY_API_VERSION}/standard-install.yaml"
echo

echo "Installing kagent CLI tool..."
curl https://raw.githubusercontent.com/kagent-dev/kagent/refs/heads/main/scripts/get-kagent | bash
echo

echo "Installing kagent components via Helm..."
helm upgrade -i kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
    --namespace $KAGENT_NAMESPACE \
    --create-namespace \
    --wait \
    --kube-context $KUBECTX_NAME

helm upgrade -i kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
    --namespace $KAGENT_NAMESPACE \
    --set providers.openAI.apiKey=$OPENAI_API_KEY \
    --wait \
    --kube-context $KUBECTX_NAME
echo

echo "Installing kgateway components via Helm..."
helm upgrade -i --create-namespace --namespace $KGATEWAY_NAMESPACE --version v${KGATEWAY_VERSION} kgateway-crds oci://cr.kgateway.dev/kgateway-dev/charts/kgateway-crds --set controller.image.pullPolicy=Always --wait
helm upgrade -i --namespace $KGATEWAY_NAMESPACE --version v${KGATEWAY_VERSION} kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway --set controller.image.pullPolicy=Always --wait
echo

# --- Observability Stack ---
echo "--- [4/7] Deploying Observability Stack..."
echo "Creating monitoring namespace and persistent volumes..."
kubectl create namespace "$MONITORING_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f manifests/monitoring/storage.yaml
echo

echo "Creating UniFi Poller secret..."
kubectl create secret generic unifi-credentials \
  --namespace "$MONITORING_NAMESPACE" \
  --from-literal=username="$UNIFI_CONTROLLER_USER" \
  --from-literal=password="$UNIFI_CONTROLLER_PASS" \
  --from-literal=url="$UNIFI_CONTROLLER_URL" \
  --dry-run=client -o yaml | kubectl apply -f -
echo

echo "Adding Helm repositories..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
echo

echo "Installing Prometheus, Loki, Blackbox Exporter, and Grafana via Helm..."

helm upgrade --install kube-prometheus prometheus-community/kube-prometheus-stack \
  --namespace "$MONITORING_NAMESPACE" \
  -f manifests/monitoring/helm/kube-prometheus-stack-values.yaml \
  --wait --timeout 10m

echo "Waiting for Prometheus CRDs to be established..."
kubectl wait --for=condition=Established crd/prometheusrules.monitoring.coreos.com --timeout=180s || true
kubectl wait --for=condition=Established crd/servicemonitors.monitoring.coreos.com --timeout=180s || true
kubectl wait --for=condition=Established crd/probes.monitoring.coreos.com --timeout=180s || true
kubectl wait --for=condition=Established crd/alertmanagers.monitoring.coreos.com --timeout=180s || true

helm upgrade --install loki grafana/loki-stack \
  -n "$MONITORING_NAMESPACE" \
  -f manifests/monitoring/helm/loki-stack-values.yaml \
  --wait --timeout 10m

helm upgrade --install blackbox prometheus-community/prometheus-blackbox-exporter \
  -n "$MONITORING_NAMESPACE" \
  --wait --timeout 5m

helm upgrade --install grafana grafana/grafana \
  --namespace monitoring \
  -f manifests/monitoring/helm/grafana-values.yaml \
  --wait --timeout 5m
echo

# --- Dashboards & Kustomize Overlays ---
echo "--- [5/7] Fetching vendor dashboards..."
scripts/vendor-unifi-dashboards.sh
echo

echo "--- [6/7] Applying Kustomize overlays for monitoring and ingress..."
kubectl apply --server-side -k manifests/monitoring/
kubectl apply --server-side -k manifests/ingress/
echo

# --- Final Status ---
echo "--- [7/7] Deployment Complete! ---"
echo
echo "Access services at http://localhost:7001"
echo "  - Grafana: http://localhost:7001/grafana"
echo "    - User: admin"
echo "    - Pass: $GRAFANA_ADMIN_PASSWORD"
echo "  - kagent UI: http://localhost:7001/kagent"
echo
echo "Syslog is listening on:"
echo "  - TCP: port $SYSLOG_PORT_TCP"
echo "  - UDP: port $SYSLOG_PORT_UDP"
echo
exit 0
