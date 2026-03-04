#!/bin/bash
# cluster-setup-k3d-observability-everything.sh
# Automates the creation of a k3d cluster with a full observability stack.
# Tom Dean

set -euo pipefail

# Ensure we run from the repository root
cd "$(dirname "$0")/.."

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
check_command jq
check_command envsubst
check_command docker

# Verify Docker is running
if ! docker info &> /dev/null; then
    echo "Error: Docker is not running. Please start Docker and try again."
    exit 1
fi

echo "All prerequisites found."
echo

# Set environment variables
source vars.sh

# --- Validate Required Variables ---
missing=()
[[ -z "$PERSISTENT_DATA_PATH" ]] && missing+=("PERSISTENT_DATA_PATH")
[[ -z "$CLUSTER_NAME" ]] && missing+=("CLUSTER_NAME")
[[ -z "$KUBECTX_NAME" ]] && missing+=("KUBECTX_NAME")
[[ -z "$K3S_VERSION" ]] && missing+=("K3S_VERSION")
if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Error: The following required variables are not set in vars.sh:"
    printf '  - %s\n' "${missing[@]}"
    exit 1
fi

if [[ "$PERSISTENT_DATA_PATH" == *" "* ]]; then
    echo "Error: PERSISTENT_DATA_PATH must not contain spaces."
    exit 1
fi

if [[ ! -d "$PERSISTENT_DATA_PATH" ]]; then
    echo "Error: PERSISTENT_DATA_PATH directory does not exist: $PERSISTENT_DATA_PATH"
    exit 1
fi

# Strip trailing slash from PERSISTENT_DATA_PATH
PERSISTENT_DATA_PATH="${PERSISTENT_DATA_PATH%/}"

# --- Cluster Setup ---
echo "--- [2/7] Setting up k3d cluster: $CLUSTER_NAME..."
echo "Deleting existing cluster (if any)..."
k3d cluster delete "$CLUSTER_NAME" || true

echo "Creating new k3d cluster..."
k3d cluster create "$CLUSTER_NAME" \
    -c cluster-k3d/k3d-cluster.yaml
k3d cluster list
echo

echo "Configuring kubectl context..."
kubectx -d "$KUBECTX_NAME" || true
kubectx "$KUBECTX_NAME=k3d-$CLUSTER_NAME"
kubectx "$KUBECTX_NAME"
kubectx
echo

# --- Core Components & CRDs ---
if [[ -n "$OPENAI_API_KEY" ]]; then
  echo "--- [3/7] Installing Core Components (Gateway API, kagent, kgateway)..."
else
  echo "--- [3/7] Installing Core Components (Gateway API, kgateway)..."
fi
echo "Installing Gateway API CRDs..."
kubectl apply --context "$KUBECTX_NAME" -f "https://github.com/kubernetes-sigs/gateway-api/releases/download/${GATEWAY_API_VERSION}/experimental-install.yaml"
echo

if [[ -n "$OPENAI_API_KEY" ]]; then
  echo "Installing kagent CLI tool..."
  curl https://raw.githubusercontent.com/kagent-dev/kagent/refs/heads/main/scripts/get-kagent | bash
  echo

  echo "Installing kagent components via Helm..."
  helm upgrade -i kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
      --version "$KAGENT_VERSION" \
      --namespace "$KAGENT_NAMESPACE" \
      --create-namespace \
      --wait \
      --kube-context "$KUBECTX_NAME"

  helm upgrade -i kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
      --version "$KAGENT_VERSION" \
      --namespace "$KAGENT_NAMESPACE" \
      --set-string providers.openAI.apiKey="$OPENAI_API_KEY" \
      --wait \
      --kube-context "$KUBECTX_NAME"
  echo
else
  echo "Skipping kagent installation (OPENAI_API_KEY not set in vars.sh)."
  echo
fi

echo "Installing kgateway components via Helm..."
helm upgrade -i --create-namespace --namespace "$KGATEWAY_NAMESPACE" --version "v${KGATEWAY_VERSION}" kgateway-crds oci://cr.kgateway.dev/kgateway-dev/charts/kgateway-crds --set controller.image.pullPolicy=Always --wait --kube-context "$KUBECTX_NAME"
helm upgrade -i --namespace "$KGATEWAY_NAMESPACE" --version "v${KGATEWAY_VERSION}" kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway --set controller.image.pullPolicy=Always --wait --kube-context "$KUBECTX_NAME"
echo

# --- Observability Stack ---
echo "--- [4/7] Deploying Observability Stack..."
echo "Creating monitoring namespace and persistent volumes..."
kubectl --context "$KUBECTX_NAME" create namespace "$MONITORING_NAMESPACE" --dry-run=client -o yaml | kubectl --context "$KUBECTX_NAME" apply -f -
envsubst '$PERSISTENT_DATA_PATH' < manifests/monitoring/storage.yaml | kubectl --context "$KUBECTX_NAME" apply --server-side -f -
echo

echo "Creating UniFi Poller secret..."
kubectl --context "$KUBECTX_NAME" create secret generic unifi-credentials \
  --namespace "$MONITORING_NAMESPACE" \
  --from-literal=username="$UNIFI_CONTROLLER_USER" \
  --from-literal=password="$UNIFI_CONTROLLER_PASS" \
  --from-literal=url="$UNIFI_CONTROLLER_URL" \
  --dry-run=client -o yaml | kubectl --context "$KUBECTX_NAME" apply -f -
echo

echo "Adding Helm repositories..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update
helm repo add grafana https://grafana.github.io/helm-charts --force-update
helm repo update
echo

echo "Installing Prometheus, Loki, Blackbox Exporter, and Grafana via Helm..."

helm upgrade --install kube-prometheus prometheus-community/kube-prometheus-stack \
  --namespace "$MONITORING_NAMESPACE" \
  -f manifests/monitoring/helm/kube-prometheus-stack-values.yaml \
  --wait --timeout 10m \
  --kube-context "$KUBECTX_NAME"

echo "Waiting for Prometheus CRDs to be established..."
kubectl --context "$KUBECTX_NAME" wait --for=condition=Established crd/prometheusrules.monitoring.coreos.com --timeout=180s
kubectl --context "$KUBECTX_NAME" wait --for=condition=Established crd/servicemonitors.monitoring.coreos.com --timeout=180s
kubectl --context "$KUBECTX_NAME" wait --for=condition=Established crd/probes.monitoring.coreos.com --timeout=180s
kubectl --context "$KUBECTX_NAME" wait --for=condition=Established crd/alertmanagers.monitoring.coreos.com --timeout=180s

helm upgrade --install loki grafana/loki-stack \
  -n "$MONITORING_NAMESPACE" \
  -f manifests/monitoring/helm/loki-stack-values.yaml \
  --wait --timeout 10m \
  --kube-context "$KUBECTX_NAME"

helm upgrade --install blackbox prometheus-community/prometheus-blackbox-exporter \
  -n "$MONITORING_NAMESPACE" \
  --wait --timeout 5m \
  --kube-context "$KUBECTX_NAME"

GRAFANA_TMP_VALUES=$(mktemp)
trap "rm -f '$GRAFANA_TMP_VALUES'" EXIT
printf 'adminPassword: "%s"\n' "$GRAFANA_ADMIN_PASSWORD" > "$GRAFANA_TMP_VALUES"
helm upgrade --install grafana grafana/grafana \
  --namespace "$MONITORING_NAMESPACE" \
  -f manifests/monitoring/helm/grafana-values.yaml \
  -f "$GRAFANA_TMP_VALUES" \
  --wait --timeout 5m \
  --kube-context "$KUBECTX_NAME"
rm -f "$GRAFANA_TMP_VALUES"
echo

# --- Dashboards & Kustomize Overlays ---
echo "--- [5/7] Fetching vendor dashboards..."
scripts/vendor-unifi-dashboards.sh
echo

echo "--- [6/7] Applying Kustomize overlays for monitoring, kgateway, and ingress..."
kubectl --context "$KUBECTX_NAME" apply --server-side -k manifests/monitoring/
envsubst '$SYSLOG_PORT_TCP' < manifests/monitoring/kgateway/syslog-gateway.yaml | kubectl --context "$KUBECTX_NAME" apply --server-side -f -
kubectl --context "$KUBECTX_NAME" apply --server-side -f manifests/monitoring/kgateway/tcp-syslog-route.yaml
kubectl --context "$KUBECTX_NAME" apply --server-side -k manifests/ingress/
if [[ -n "$OPENAI_API_KEY" ]]; then
  kubectl --context "$KUBECTX_NAME" apply --server-side -f manifests/ingress/kagent-httproute.yaml
fi
echo

# --- Final Status ---
echo "--- [7/7] Deployment Complete! ---"
echo
echo "Access services at http://localhost:7001"
echo "  - Grafana: http://localhost:7001/grafana"
echo "    - User: admin"
echo "    - Pass: (set in vars.sh as GRAFANA_ADMIN_PASSWORD)"
if [[ -n "$OPENAI_API_KEY" ]]; then
  echo "  - kagent UI: http://localhost:7001/kagent"
fi
echo
echo "Syslog is listening on:"
echo "  - TCP: port $SYSLOG_PORT_TCP"
echo
exit 0
