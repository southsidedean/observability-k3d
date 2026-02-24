#!/usr/bin/env bash
# Standalone helper for rotating the UniFi credentials secret
# outside of the full cluster setup flow.
# The main setup script (cluster-setup-k3d-observability-everything.sh)
# creates this secret automatically during initial deployment.
set -euo pipefail
NAMESPACE=${NAMESPACE:-monitoring}

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <unifi-username> <unifi-password> <unifi-controller-url>"
  echo "  Example: $0 unifipoller mypassword https://unifi.example.com"
  exit 1
fi

USER="$1"
PASS="$2"
URL="$3"

kubectl -n "$NAMESPACE" delete secret unifi-credentials --ignore-not-found
kubectl -n "$NAMESPACE" create secret generic unifi-credentials \
  --from-literal=username="$USER" \
  --from-literal=password="$PASS" \
  --from-literal=url="$URL"

echo "Created secret 'unifi-credentials' in namespace $NAMESPACE"
