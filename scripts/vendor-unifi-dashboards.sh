#!/usr/bin/env bash
set -euo pipefail

DASH_DIR="manifests/monitoring/dashboards/unifi"
mkdir -p "$DASH_DIR"

# IDs to fetch
IDS=(11310 11311 11312 11313 11314 11315)

for id in "${IDS[@]}"; do
  # allow pinning via env, e.g., GRAFANA_REVISION_11311=7
  REV_VAR="GRAFANA_REVISION_${id}"
  REV="${!REV_VAR:-latest}"

  # Discover latest revision if not pinned
  if [[ "$REV" == "latest" ]]; then
    REV=$(curl -fsSL "https://grafana.com/api/dashboards/${id}/revisions" |
      jq -r '.items[-1].revision')
  fi

  if [[ -z "$REV" || "$REV" == "null" ]]; then
    echo "Could not determine revision for dashboard ${id}; trying 1"
    REV=1
  fi

  echo "Fetching dashboard ${id} rev ${REV} ..."
  DASH_FILE="${DASH_DIR}/unpoller-dashboard-${id}.json"
  curl -fsSL "https://grafana.com/api/dashboards/${id}/revisions/${REV}/download" -o "$DASH_FILE"

  echo "Patching dashboard ${id} to use correct prometheus datasource..."
  # Use sed to replace the placeholder datasource variable with the hardcoded 'prometheus' uid.
  sed -i.bak 's/${DS_PROMETHEUS}/prometheus/g' "$DASH_FILE" && rm "$DASH_FILE.bak"

  # Ensure a small JSON exists (basic validation)
  test -s "${DASH_DIR}/unpoller-dashboard-${id}.json"
done

echo "Dashboards saved to ${DASH_DIR}"
