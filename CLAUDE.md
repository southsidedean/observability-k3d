# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Kubernetes observability stack for home lab environments, deployed on k3d (Kubernetes in Docker). Provides automated setup of Prometheus, Grafana, Loki, and Promtail with specialized monitoring for UniFi network equipment and Plex media servers.

## Key Commands

### Cluster Lifecycle
```bash
# Full cluster setup (7-stage pipeline: prereqs → cluster → core → observability → dashboards → kustomize → status)
./scripts/cluster-setup-k3d-observability-everything.sh

# Destroy cluster
./scripts/cluster-destroy-k3d.sh

# Fetch/update UniFi dashboards from Grafana.com
./scripts/vendor-unifi-dashboards.sh
```

### Working with Manifests
```bash
# Apply a specific kustomize overlay after changes
kubectl apply -k manifests/monitoring/grafana/
kubectl apply -k manifests/monitoring/prometheus/
kubectl apply -k manifests/monitoring/alerts/
kubectl apply -k manifests/monitoring/probes/
kubectl apply -k manifests/monitoring/unifi/
kubectl apply -k manifests/monitoring/kgateway/
kubectl apply -k manifests/ingress/
```

### Prerequisites (validated by setup script)
k3d, Docker, Helm 3, kubectl, kubectx, curl, jq

## Architecture

### Deployment Pipeline
The setup script (`scripts/cluster-setup-k3d-observability-everything.sh`) orchestrates a 7-stage deploy:
1. Prerequisite checks
2. k3d cluster creation (1 server, 3 agents) from `cluster-k3d/k3d-cluster.yaml`
3. Core components: Gateway API CRDs, kagent, kgateway
4. Observability stack via Helm: kube-prometheus-stack, loki-stack, blackbox-exporter, grafana
5. Vendor dashboard fetching (UniFi dashboards from Grafana.com API)
6. Kustomize overlays for all component manifests
7. Status output with access URLs

### Configuration
- **`vars.sh`** — Central config file sourced by all scripts. Contains cluster name, versions, namespaces, credentials, and paths. Must be edited before first run (especially `PERSISTENT_DATA_PATH` and UniFi credentials).
- **Helm values** — `manifests/monitoring/helm/` contains values files for each Helm chart
- **Kustomize overlays** — Each component directory has a `kustomization.yaml`

### Namespaces
- `monitoring` — Prometheus, Grafana, Loki, Promtail, Unpoller, Blackbox
- `kagent` — AI-assisted Kubernetes operations
- `kgateway-system` — Ingress controller

### Storage
Persistent volumes use hostPath mounts to `$PERSISTENT_DATA_PATH` on the host (default `/media/content/observability-k3d/`):
- `grafana-pv` (10Gi), `loki-pv` (10Gi) — defined in `manifests/monitoring/storage.yaml` (templated with `$PERSISTENT_DATA_PATH`, expanded via `envsubst` at deploy time)
- Prometheus PV is managed dynamically by the kube-prometheus-stack Helm chart via `local-path` StorageClass

### Ingress (Gateway API)
- HTTP Gateway on port 80 (mapped to host 7001): routes for `/grafana` and `/kagent`
- TCP Gateway on port 30114: syslog ingestion via kgateway → Promtail (port 1514)
- Defined in `manifests/ingress/` and `manifests/monitoring/kgateway/`

### Syslog Pipeline
External hosts forward syslog → host:30114 (TCP) → kgateway TCPRoute → Promtail syslog listener (1514) → Loki. Labels extracted: `host`, `app`. Example rsyslog config in `extras/rsyslog-forward-example.conf`.

### Dashboards
- `manifests/monitoring/dashboards/unifi/` — Vendored from Grafana.com (IDs 11310-11315), auto-patched by `scripts/vendor-unifi-dashboards.sh`
- `manifests/monitoring/dashboards/plex/` — Plex media server dashboards (currently disabled — uncomment entries in `dashboards/kustomization.yaml` to enable)
- `manifests/monitoring/dashboards/custom-dashboards.yaml` — Loki overview and Active Alerts

### Alert Rules
- `manifests/monitoring/alerts/prometheus-rules.yaml` — System alerts (NodeDown, HighCPU, HighMemory, DiskFilling)
- `manifests/monitoring/alerts/unifi-rules.yaml` — UniFi device alerts (offline, high CPU/memory)

## Conventions

- All environment config goes in `vars.sh`, never hardcoded in scripts
- Grafana dashboards are stored as JSON in ConfigMaps (one dashboard per file in `dashboards/`)
- UniFi dashboards are vendored (fetched from external API), not hand-written — edit `vendor-unifi-dashboards.sh` to change revisions
- Helm chart configuration is separated from Kustomize: Helm values in `manifests/monitoring/helm/`, Kustomize overlays for raw K8s resources
- The setup script is idempotent — Helm uses `--install` flag, kubectl uses `apply`
