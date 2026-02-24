#!/bin/bash
# cluster-destroy-k3d.sh
# Automates cluster deletion and cleans up the kubectl contexts
# Tom Dean
# Last edit: 2/23/2026

set -euo pipefail

# Ensure we run from the repository root
cd "$(dirname "$0")/.."

# Set environment variables
source vars.sh

if [[ -z "$CLUSTER_NAME" ]]; then
    echo "Error: CLUSTER_NAME is not set in vars.sh."
    exit 1
fi

# Remove the k3d cluster
k3d cluster delete "$CLUSTER_NAME"
k3d cluster list

# Remove the kubectl context
kubectx -d "$KUBECTX_NAME" || true
kubectx

echo "Cluster deleted!"

exit 0
