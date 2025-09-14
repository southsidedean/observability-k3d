#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME=${CLUSTER_NAME:-homelab}
HOST_PATH=${HOST_PATH:-/media/content/observability-k3d}

k3d cluster create "$CLUSTER_NAME" \
  --agents 1 \
  --port "30000-30100:30000-30100@server:0" \
  --api-port 6445 \
  --kubeconfig-switch-context \
  --wait \
  --volume "${HOST_PATH}:${HOST_PATH}@all"

kubectl config view --minify --raw > "${HOME}/.kube/k3d-${CLUSTER_NAME}-config"
echo "Cluster ${CLUSTER_NAME} created. Kubeconfig: ${HOME}/.kube/k3d-${CLUSTER_NAME}-config"
