#!/usr/bin/env bash
set -euo pipefail
NAMESPACE=${NAMESPACE:-monitoring}

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <unifi-username> <unifi-password>"
  exit 1
fi

USER="$1"
PASS="$2"

kubectl -n "$NAMESPACE" delete secret unifi-credentials --ignore-not-found
kubectl -n "$NAMESPACE" create secret generic unifi-credentials \
  --from-literal=username="$USER" \
  --from-literal=password="$PASS"

echo "Created secret 'unifi-credentials' in namespace $NAMESPACE"
