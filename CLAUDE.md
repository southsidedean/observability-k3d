# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Kubernetes observability stack for home lab environments, deployed on k3d (Kubernetes in Docker). Shell scripts plus Helm values and Kustomize manifests stand up Prometheus, Grafana, Loki, Promtail, Blackbox Exporter, and Unpoller (UniFi metrics), with kgateway for ingress and optional kagent. There is no build step or test suite.

## Key Commands

```bash
# Full deploy. Deletes and recreates the k3d cluster every run, by design: recreating
# with newer versions is the upgrade path, and state survives on host folders (see Storage).
./scripts/cluster-setup-k3d-observability-everything.sh

# Destroy cluster
./scripts/cluster-destroy-k3d.sh

# Re-fetch UniFi dashboards from Grafana.com (pin a revision with GRAFANA_REVISION_<id>=N)
./scripts/vendor-unifi-dashboards.sh

# Rotate the UniFi credentials secret without a full redeploy
./extras/create-unifi-secret.sh <user> <pass> <controller-url>
```

### Applying manifest changes to a running cluster
Mirror what the setup script does (server-side apply, explicit context):
```bash
source vars.sh
kubectl --context "$KUBECTX_NAME" apply --server-side -k manifests/monitoring/   # prometheus, probes, alerts, grafana, dashboards, unifi
kubectl --context "$KUBECTX_NAME" apply --server-side -k manifests/ingress/

# These contain $VARS and must go through envsubst, NOT `kubectl apply -k`:
envsubst '$PERSISTENT_DATA_PATH' < manifests/monitoring/storage.yaml | kubectl --context "$KUBECTX_NAME" apply --server-side -f -
envsubst '$SYSLOG_PORT_TCP' < manifests/monitoring/kgateway/syslog-gateway.yaml | kubectl --context "$KUBECTX_NAME" apply --server-side -f -
kubectl --context "$KUBECTX_NAME" apply --server-side -f manifests/monitoring/kgateway/tcp-syslog-route.yaml

# Helm value changes: re-run the matching `helm upgrade --install` from the setup script
```

### Validating changes (no tests exist)
```bash
kubectl kustomize manifests/monitoring/   # render without applying
bash -n scripts/*.sh                      # shell syntax check
```

## Architecture

### Deployment pipeline (`scripts/cluster-setup-k3d-observability-everything.sh`)
1. Prereq checks (k3d, helm, kubectl, kubectx, curl, jq, envsubst, docker) and `vars.sh` validation (`PERSISTENT_DATA_PATH` must exist and contain no spaces)
2. `k3d cluster delete` then create from `cluster-k3d/k3d-cluster.yaml` (1 server, 3 agents, traefik disabled). The k3d config references `$CLUSTER_NETWORK`, `$K3S_VERSION`, `$SYSLOG_PORT_TCP`, `$PERSISTENT_DATA_PATH`, so `vars.sh` must be sourced
3. Gateway API CRDs (experimental channel, for TCPRoute), kgateway; kagent only if `OPENAI_API_KEY` is set
4. `monitoring` namespace, PVs/PVCs, `unifi-credentials` secret, then Helm: kube-prometheus-stack → loki-stack → blackbox-exporter → grafana. Grafana is a separate chart, not the one bundled with kube-prometheus-stack
5. `vendor-unifi-dashboards.sh`, which overwrites the committed JSON in `dashboards/unifi/` with the latest Grafana.com revisions on every deploy
6. Kustomize/manifest apply (see commands above); `kagent-httproute.yaml` is applied only when `OPENAI_API_KEY` is set
7. Print access URLs

Secrets (Grafana admin password, OpenAI key) are passed to Helm via temp values files, never on the command line.

### Configuration
- **`vars.sh`**: all environment config (cluster name, versions, namespaces, credentials, ports, paths). Never hardcode these in scripts or manifests; use `envsubst` with an explicit variable list if a manifest needs one.
- **Helm values**: `manifests/monitoring/helm/`
- **Kustomize**: `manifests/monitoring/kustomization.yaml` aggregates prometheus, probes, alerts, grafana, dashboards, unifi (namespace forced to `monitoring`). `storage.yaml` and `kgateway/` are deliberately outside it because they need `envsubst`.

### Host ports (k3d loadbalancer)
- 7001 → HTTP Gateway (80): `/grafana`, `/kagent`
- 7401 → 443, 7601 → Kubernetes API
- `$SYSLOG_PORT_TCP` (30114) → syslog TCP Gateway

### Storage
The cluster is disposable and the data is not: anything stateful must live under `$PERSISTENT_DATA_PATH` so a recreated cluster picks up where it left off.
- `grafana-pv`, `loki-pv` (10Gi each): hostPath under `$PERSISTENT_DATA_PATH`, which k3d mounts into every node at the same path. Reclaim policy `Retain`, pre-bound to their PVCs.
- Prometheus (20Gi, 15d retention) currently uses dynamic `local-path` storage inside the k3d containers, so its data is lost on recreate. The dedicated `prometheus-pv` that used to keep it on the host was removed in `2e1b018` and needs restoring.

### Grafana wiring
- Served from a sub-path (`GF_SERVER_ROOT_URL=http://localhost:7001/grafana/`, `SERVE_FROM_SUB_PATH`)
- Sidecars load ConfigMaps from all namespaces by label: `grafana_dashboard: "1"`, `grafana_datasource: "1"`, `grafana_alert: "1"`
- The Prometheus datasource has fixed `uid: prometheus`. Vendored UniFi dashboards depend on this: the vendor script rewrites `${DS_PROMETHEUS}` to `prometheus`. Changing the uid breaks them.
- Grafana-managed alert rules live in `manifests/monitoring/grafana/alerts.yaml`; contact points (`alerting.yaml`) are commented out in its kustomization until real email/Slack settings are filled in.

### Prometheus
- Rules: `manifests/monitoring/alerts/` (PrometheusRule CRs for system and UniFi alerts)
- Blackbox probes: `manifests/monitoring/probes/` (Probe CRs for DNS, gateway, websites)
- External node-exporter targets: add IPs to the `additional-scrape-configs` Secret in `manifests/monitoring/prometheus/additional-scrape-configs.yaml` (wired in via `additionalScrapeConfigsSecret` in the Helm values)
- Unpoller: `manifests/monitoring/unifi/` (Deployment, Service, ServiceMonitor), reads credentials from the `unifi-credentials` secret

### Logs
- Promtail (from loki-stack) scrapes all pod logs plus a syslog listener on 1514
- Syslog path: external host → host:30114 TCP → kgateway TCPRoute → Promtail 1514 → Loki. Labels `host` and `app` come from the syslog hostname/app name. Query with `{job="syslog", host="<device>"}`. Example sender config: `extras/rsyslog-forward-example.conf`

### Dashboards (`manifests/monitoring/dashboards/`)
- JSON files are turned into labeled ConfigMaps via `configMapGenerator` (`disableNameSuffixHash: true`); a new dashboard needs a generator entry
- `unifi/`: vendored (Grafana.com IDs 11310–11315); change behavior in the vendor script, don't hand-edit the JSON
- `plex/`: present but disabled (commented generator entries)
- `custom-dashboards.yaml`, `node-exporter-dashboard.yaml`: hand-maintained ConfigMaps
