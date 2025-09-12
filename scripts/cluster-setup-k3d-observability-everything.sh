#!/bin/bash
# cluster-setup-k3d-observability-everything.sh
# Automates k3d cluster creation
# Tom Dean
# Last edit: 9/12/2025

# Set environment variables

source vars.sh

# Delete existing k3d cluster

k3d cluster delete $CLUSTER_NAME

# Create the k3d cluster

k3d cluster create $CLUSTER_NAME -c cluster-k3d/k3d-cluster.yaml --port 7001:80@loadbalancer --port 7401:443@loadbalancer --api-port 0.0.0.0:7601
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

helm install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
    --namespace $KAGENT_NAMESPACE \
    --create-namespace \
    --kube-context $KUBECTX_NAME
echo
helm install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
    --namespace $KAGENT_NAMESPACE \
    --set providers.openAI.apiKey=$OPENAI_API_KEY \
    --kube-context $KUBECTX_NAME
echo
watch -n 1 kubectl get all -n $KAGENT_NAMESPACE --context $KUBECTX_NAME
echo

# Install the Kubernetes Gateway API CRDs

kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/${GATEWAY_API_VERSION}/standard-install.yaml
echo

# Install 'kgateway' CRDs using Helm

helm upgrade -i --create-namespace --namespace $KGATEWAY_NAMESPACE --version v${KGATEWAY_VERSION} kgateway-crds oci://cr.kgateway.dev/kgateway-dev/charts/kgateway-crds --set controller.image.pullPolicy=Always
echo

# Install 'kgateway' using Helm

helm upgrade -i --namespace $KGATEWAY_NAMESPACE --version v${KGATEWAY_VERSION} kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway --set controller.image.pullPolicy=Always
echo

# Check our 'kgateway' installation

watch -n 1 kubectl get all -n $KGATEWAY_NAMESPACE
echo

# Create an HTTP listener

kubectl apply -f manifests/http-listener.yaml
echo
kubectl get gateways -A
echo

# Create an HTTPRoute for 'kagent'

kubectl apply -f manifests/kagent-httproute.yaml
echo
kubectl get httproute -A
echo

exit 0
