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
echo "Creating local directory for persistent data in $PERSISTENT_DATA_PATH..."
# The user running this script needs write permissions to the parent directory of PERSISTENT_DATA_PATH.
# If this path is in a privileged location (e.g., /media), you may need to create it manually with 'sudo' first.
mkdir -p $PERSISTENT_DATA_PATH
echo

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

echo "Installing Observability Stack (Prometheus, Grafana, Loki)..."
echo "This may take a few minutes."

# Add Helm repos
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add unifi-poller https://unpoller.github.io/helm-chart
helm repo update

# Install kube-prometheus-stack
echo "Installing kube-prometheus-stack..."
helm upgrade -i kube-prometheus-stack prometheus-community/kube-prometheus-stack \
    --namespace $MONITORING_NAMESPACE \
    --create-namespace \
    -f manifests/monitoring/kube-prometheus-stack-values.yaml \
    --set grafana.adminPassword=$GRAFANA_ADMIN_PASSWORD \
    --wait \
    --kube-context $KUBECTX_NAME

# Install loki-stack
# NOTE: Ensure grafana is disabled in your loki-stack-values.yaml to avoid conflicts
# with the Grafana from kube-prometheus-stack.
# e.g., in loki-stack-values.yaml:
# grafana:
#   enabled: false
echo "Installing loki-stack..."
helm upgrade -i loki grafana/loki-stack \
    --namespace $MONITORING_NAMESPACE \
    -f manifests/monitoring/loki-stack-values.yaml \
    --wait \
    --kube-context $KUBECTX_NAME

echo "Installing unpoller for UniFi metrics..."
helm upgrade -i unpoller unifi-poller/unpoller \
    --namespace $MONITORING_NAMESPACE \
    -f manifests/monitoring/unpoller-values.yaml \
    --set "unifi.url=$UNIFI_CONTROLLER_URL" \
    --set "unifi.user=$UNIFI_CONTROLLER_USER" \
    --set "unifi.pass=$UNIFI_CONTROLLER_PASS" \
    --wait \
    --kube-context $KUBECTX_NAME

echo "Observability stack installation complete. Current status:"
kubectl get all -n $MONITORING_NAMESPACE --context $KUBECTX_NAME
echo "You can watch the status with: watch -n 1 kubectl get all -n $MONITORING_NAMESPACE --context $KUBECTX_NAME"
echo "It may take a few minutes for all pods to become ready."
echo

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

kubectl apply -f manifests/http-listener.yaml
echo
kubectl get gateways -A
echo

# Create an HTTPRoute for 'kagent'

kubectl apply -f manifests/kagent-httproute.yaml
echo

# Apply custom monitoring resources
echo "Applying custom monitoring resources (Probes, Alerts, Dashboards)..."
kubectl apply -k manifests/monitoring/probes --context $KUBECTX_NAME
kubectl apply -k manifests/monitoring/alerts --context $KUBECTX_NAME
kubectl apply -k manifests/monitoring/dashboards --context $KUBECTX_NAME
# Create an HTTPRoute for 'grafana'

kubectl apply -f manifests/monitoring/grafana-httproute.yaml
echo

kubectl get httproute -A
echo

echo "Grafana should be available at http://localhost:7001/grafana"
echo "Login with user 'admin' and password '$GRAFANA_ADMIN_PASSWORD'."
echo
echo "Syslog is exposed on TCP port $SYSLOG_PORT on your host."
echo "Configure your devices to send syslog to tcp://<your_host_ip>:$SYSLOG_PORT"
echo "UniFi dashboards have been added to Grafana."

exit 0
