#!/bin/bash
# cluster-setup-k3d-observability-everything.sh
# Automates k3d cluster creation
# Tom Dean
# Last edit: 9/12/2025

# --- Helper Functions ---

check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo "Error: '$1' command not found. Please install it and ensure it's in your PATH."
        exit 1
    fi
}

# --- Prerequisite Checks ---

check_command k3d
check_command helm
check_command kubectl
check_command kubectx
check_command curl

# Set environment variables

source vars.sh

# Delete existing k3d cluster

k3d cluster delete $CLUSTER_NAME

# Create local directory for persistent data if it doesn't exist
#echo "Creating local directory for persistent data in $PERSISTENT_DATA_PATH..."
# The user running this script needs write permissions to the parent directory of PERSISTENT_DATA_PATH.
# If this path is in a privileged location (e.g., /media), you may need to create it manually with 'sudo' first.
#mkdir -p $PERSISTENT_DATA_PATH
#echo

# Create the k3d cluster

k3d cluster create $CLUSTER_NAME \
    -c cluster-k3d/k3d-cluster.yaml \
    --port 7001:80@loadbalancer \
    --port 7401:443@loadbalancer \
    --port "$SYSLOG_PORT:$SYSLOG_PORT/tcp@loadbalancer" \
    --volume "$PERSISTENT_DATA_PATH:/var/lib/rancher/k3s/storage@all" \
    --api-port 0.0.0.0:7601
k3d cluster list

# Configure the kubectl context(s)

kubectx -d $KUBECTX_NAME
kubectx $KUBECTX_NAME=k3d-$CLUSTER_NAME
kubectx $KUBECTX_NAME
kubectx

# Install the 'kagent' CLI tool
# Download/run the install script

curl https://raw.githubusercontent.com/kagent-dev/kagent/refs/heads/main/scripts/get-kagent | bash
echo

# Install 'kagent' using Helm

helm upgrade -i kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
    --namespace $KAGENT_NAMESPACE \
    --create-namespace \
    --wait \
    --kube-context $KUBECTX_NAME
echo
helm upgrade -i kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
    --namespace $KAGENT_NAMESPACE \
    --set providers.openAI.apiKey=$OPENAI_API_KEY \
    --wait \
    --kube-context $KUBECTX_NAME
echo "kagent installation complete. Current status:"
kubectl get all -n $KAGENT_NAMESPACE --context $KUBECTX_NAME
echo "You can watch the status with: watch -n 1 kubectl get all -n $KAGENT_NAMESPACE --context $KUBECTX_NAME"
echo

# --- Observability Stack ---

#echo "Installing Observability Stack (Prometheus, Grafana, Loki)..."
#echo "This may take a few minutes."

# ChatGPT Stuff Start

# Namespace
#kubectl apply -f manifests/monitoring/unifi/namespace.yaml

# Patch local-path-provisioner to use host directory
#echo "Patching local-path-provisioner to use /media/content/observability-k3d/local-path-storage ..."
#kubectl apply -f manifests/storage/local-path-config-patch.yaml

# Add helm repos
#helm repo add grafana https://grafana.github.io/helm-charts >/dev/null 2>&1 || true
#helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
#helm repo add grafana-loki https://grafana.github.io/helm-charts >/dev/null 2>&1 || true
#helm repo update

# Deploy Prometheus stack
#helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
#  --namespace monitoring --create-namespace \
#  -f manifests/monitoring/prometheus-values.yaml

# Deploy Loki+Promtail
#helm upgrade --install loki-stack grafana/loki-stack \
#  --namespace monitoring \
#  -f manifests/monitoring/loki-stack-values.yaml

# Deploy Grafana (standalone, since kube-prom-stack grafana is disabled)
#helm upgrade --install grafana grafana/grafana \
#  --namespace monitoring \
#  -f manifests/grafana-values.yaml

# Vendor dashboards (fetch JSONs) then kustomize apply to create ConfigMaps
#scripts/vendor-unifi-dashboards.sh

# Unpoller resources + dashboard configmaps
#kubectl apply -k manifests/monitoring

# kgateway routes
#kubectl apply -f manifests/gateway/monitoring-httproutes.yaml

#echo "Done. Visit http://localhost:7001/grafana (admin/admin)"

# ChatGPT Stuff End

# Add Helm repos
#helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
#helm repo add grafana https://grafana.github.io/helm-charts
#helm repo add unpoller https://unpoller.github.io/helm-chart
#helm repo update

# Install kube-prometheus-stack
#echo "Installing kube-prometheus-stack..."
#helm upgrade -i kube-prometheus-stack prometheus-community/kube-prometheus-stack \
#    --namespace $MONITORING_NAMESPACE \
#    --create-namespace \
#    -f manifests/monitoring/kube-prometheus-stack-values.yaml \
#    --set grafana.adminPassword=$GRAFANA_ADMIN_PASSWORD \
#    --wait \
#    --kube-context $KUBECTX_NAME

# Install loki-stack
# NOTE: Ensure grafana is disabled in your loki-stack-values.yaml to avoid conflicts
# with the Grafana from kube-prometheus-stack.
# e.g., in loki-stack-values.yaml:
# grafana:
#   enabled: false
#echo "Installing loki-stack..."
#helm upgrade -i loki grafana/loki-stack \
#    --namespace $MONITORING_NAMESPACE \
#    -f manifests/monitoring/loki-stack-values.yaml \
#    --wait \
#    --kube-context $KUBECTX_NAME

# Install unpoller for UniFi metrics
#echo "Installing unpoller for UniFi metrics..."
#kubectl apply -f manifests/monitoring/unpoller.yaml

# helm upgrade -i unpoller unpoller/unpoller \
#    --namespace $MONITORING_NAMESPACE \
#    -f manifests/monitoring/unpoller-values.yaml \
#    --wait \
#    --kube-context $KUBECTX_NAME

#helm upgrade -i unpoller unifi-poller/unpoller \
#    --namespace $MONITORING_NAMESPACE \
#    -f manifests/monitoring/unpoller-values.yaml \
#    --set "unifi.url=$UNIFI_CONTROLLER_URL" \
#    --set "unifi.user=$UNIFI_CONTROLLER_USER" \
#    --set "unifi.pass=$UNIFI_CONTROLLER_PASS" \
#    --wait \
#    --kube-context $KUBECTX_NAME

#echo "Observability stack installation complete. Current status:"
#kubectl get all -n $MONITORING_NAMESPACE --context $KUBECTX_NAME
#echo "You can watch the status with: watch -n 1 kubectl get all -n $MONITORING_NAMESPACE --context $KUBECTX_NAME"
#echo "It may take a few minutes for all pods to become ready."
#echo

# Install the Kubernetes Gateway API CRDs

kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/${GATEWAY_API_VERSION}/standard-install.yaml
echo

# Install 'kgateway' CRDs using Helm

helm upgrade -i --create-namespace --namespace $KGATEWAY_NAMESPACE --version v${KGATEWAY_VERSION} kgateway-crds oci://cr.kgateway.dev/kgateway-dev/charts/kgateway-crds --set controller.image.pullPolicy=Always --wait
echo

# Install 'kgateway' using Helm

helm upgrade -i --namespace $KGATEWAY_NAMESPACE --version v${KGATEWAY_VERSION} kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway --set controller.image.pullPolicy=Always --wait
echo

# Check our 'kgateway' installation

echo "kgateway installation complete. Current status:"
kubectl get all -n $KGATEWAY_NAMESPACE
echo "You can watch the status with: watch -n 1 kubectl get all -n $KGATEWAY_NAMESPACE"
echo

# Create an HTTP listener

#kubectl apply -f manifests/http-listener.yaml
#echo
#kubectl get gateways -A
#echo

# Create an HTTPRoute for 'kagent'

kubectl apply -f manifests/kagent-httproute.yaml
echo

# Apply custom monitoring resources
#echo "Applying custom monitoring resources (Probes, Alerts, Dashboards)..."
#kubectl apply -k manifests/monitoring/probes --context $KUBECTX_NAME
#kubectl apply -k manifests/monitoring/alerts --context $KUBECTX_NAME
#kubectl apply -k manifests/monitoring/dashboards --context $KUBECTX_NAME
# Create an HTTPRoute for 'grafana'

#kubectl apply -f manifests/monitoring/grafana-httproute.yaml
#echo

#kubectl get httproute -A
#echo

#echo "Grafana should be available at http://localhost:7001/grafana"
#echo "Login with user 'admin' and password '$GRAFANA_ADMIN_PASSWORD'."
#echo
#echo "Syslog is exposed on TCP port $SYSLOG_PORT on your host."
#echo "Configure your devices to send syslog to tcp://<your_host_ip>:$SYSLOG_PORT"
#echo "UniFi dashboards have been added to Grafana."

# Deploy observability stack
# Create Unpoller secret

./extras/create-unifi-secret.sh $UNIFI_CONTROLLER_USER $UNIFI_CONTROLLER_PASS

# Helm stuff first

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

# 
exit 0
