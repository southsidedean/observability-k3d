#!/usr/bin/env bash
set -euo pipefail
CLUSTER_NAME=${CLUSTER_NAME:-homelab}
k3d cluster delete "$CLUSTER_NAME" || true
