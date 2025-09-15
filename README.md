# observability-k3d

## Introduction

This repository provides scripts and manifests to quickly stand up a local Kubernetes cluster using `k3d` with a comprehensive observability stack. The stack is designed for home lab environments, particularly those using Ubiquiti UniFi network gear.

The following components are installed:
- **Prometheus:** For metrics collection and alerting.
- **Grafana:** For visualization and dashboards.
- **Loki:** For log aggregation.
- **Promtail:** For shipping logs to Loki, including a syslog listener.
- **Unpoller:** For exporting detailed metrics from a UniFi Controller to Prometheus.
- **kagent & kgateway:** For AI-assisted Kubernetes operations and simplified ingress.

Data for Prometheus, Grafana, and Loki is persisted to a local directory on your host machine to survive cluster restarts.

## Prerequisites

If you don't have the following, you're gonna have a bad time:

- [`k3d`](https://k3d.io)
- [Docker](https://www.docker.com/get-started/)
- [Helm](https://helm.sh/docs/intro/install/)
- The `bash` (or equivalent) shell
- [The `kubectl` command](https://kubernetes.io/docs/tasks/tools/)
- [The `kubectx` command](https://github.com/ahmetb/kubectx)
- [The `curl` command](https://curl.se/download.html)
- The `watch` command
- The contents of [this](https://github.com/southsidedean/observability-k3d) GitHub repository
- Internet access to pull containers

Everything else is self-contained, just run the script to create the cluster(s).

### Configuration

Before running the setup script, you must configure the environment variables in `vars.sh`:

- `PERSISTENT_DATA_PATH`: The local directory on your host machine where monitoring data will be stored (e.g., `/media/content/observability`).
- `UNIFI_CONTROLLER_URL`, `UNIFI_CONTROLLER_USER`, `UNIFI_CONTROLLER_PASS`: Credentials for a **read-only** user on your UniFi Controller.
- `OPENAI_API_KEY`: (Optional) Your API key for OpenAI if you intend to use the AI features of `kagent`.

### Usage
The primary script `scripts/cluster-setup-k3d-observability-everything.sh` automates the entire process.

1.  **Configure variables:** Edit `vars.sh` as described above.
2.  **Run the script:**
    ```bash
    ./scripts/cluster-setup-k3d-observability-everything.sh
    ```
This script will:
- Create a local directory for persistent data.
- Create a `k3d` cluster with the necessary ports and volume mounts.
- Install `kagent` and `kgateway`.
- Deploy the full observability stack (Prometheus, Grafana, Loki, Unpoller).
- Apply custom monitoring rules and gateway routes.

#### Other Scripts

- **Destroy Cluster:** To tear down the cluster and its resources, use `scripts/cluster-destroy-k3d.sh`.
- **Naked Cluster:** For advanced users who want to build their own setup, `scripts/cluster-setup-k3d-naked.sh` creates a cluster with `k3d` but does not deploy any of the observability or `kagent` components.

To destroy the cluster, use the `scripts/cluster-destroy-k3d.sh` script.

### Accessing Services

Once the script is complete, you can access the services via the `kgateway` ingress running on `localhost:7001`:

- **Grafana:** `http://localhost:7001/grafana`
  - **Login:** `admin` / password set in `GRAFANA_ADMIN_PASSWORD` from `vars.sh`.
- **kagent UI:** `http://localhost:7001/kagent`
- **Syslog:** Your host machine will listen for syslog messages on TCP port `1514` (or as configured in `SYSLOG_PORT`). Configure your devices (like UniFi gear or Ubuntu servers) to send logs to `tcp://<your_host_ip>:1514`.

### Monitoring Capabilities

#### Querying Syslog Data in Grafana

The system is configured to separate logs from each device. In Grafana's "Explore" view with the Loki data source, you can query for logs from a specific host using its `host` label.

For example, to see logs from a device named `unifi-dream-machine`, use the following LogQL query:

`{job="syslog", host="unifi-dream-machine"}`

### Monitoring External Hosts (e.g., Ubuntu Servers)

This stack is pre-configured to monitor external Linux hosts using Prometheus `node-exporter`.

1.  **Install Node Exporter:** On each Ubuntu server you want to monitor, install and enable the `node-exporter` service.
    ```bash
    sudo apt-get install prometheus-node-exporter
    sudo systemctl start node-exporter
    sudo systemctl enable node-exporter
    ```
    Verify it's running by visiting `http://<your_ubuntu_ip>:9100/metrics`.

2.  **Configure Prometheus:** Open `manifests/monitoring/kube-prometheus-stack-values.yaml`. Find the `additionalScrapeConfigs` section and add the IP addresses and port (`9100`) of your Ubuntu servers to the `targets` list.

3.  **Re-run the setup script:** Execute `./scripts/cluster-setup-k3d-observability-everything.sh` again to apply the new configuration.

Once complete, the "Node Exporter Full" dashboard will be populated with metrics from your servers, and the new host-level alerts will be active.
#### UniFi Dashboards

The `unpoller` component automatically installs a comprehensive set of Grafana dashboards for your UniFi devices. Look for dashboards with "UniFi" in the title in your Grafana instance.

### Repository Structure

```bash
observability-k3d/
├── README.md
├── cluster-k3d
│   └── k3d-cluster.yaml
├── manifests
│   ├── dashboards
│   │   ├── blackbox-exporter-dashboard.yaml
│   │   └── node-exporter-dashboard.yaml
│   ├── http-listener.yaml
│   ├── kagent-httproute.yaml
│   ├── monitoring
│   │   ├── alerts
│   │   ├── grafana-httproute.yaml
│   │   ├── kube-prometheus-stack-values.yaml
│   │   ├── loki-stack-values.yaml
│   │   ├── probes
│   │   └── unpoller-values.yaml
├── scripts
│   ├── cluster-destroy-k3d.sh
│   ├── cluster-setup-k3d-naked.sh
│   └── cluster-setup-k3d-observability-everything.sh
└── vars.sh
```

If you want to tweak the variables for the scripts, look in the `vars.sh` file.

You should use the included scripts to create cluster(s) for local testing:

```bash
scripts
├── cluster-destroy-k3d.sh
├── cluster-setup-k3d-kagent-everything.sh
└── cluster-setup-k3d-naked.sh
```

Several options exist for deploying cluster(s):

- One or more clusters (configure in `vars.sh`), with kagent and kgateway deployed (`cluster-setup-k3d-kagent-everything.sh`)
- A "naked" cluster, no kagent or kgateway (`cluster-setup-k3d-naked.sh`)
  - You'll need to deploy kagent and the "extras" yourself
  - Great for building your own!
- A script to tear down your cluster(s).

### About kagent

The `kagent` dashboard can be accessed on your local machine, via `http://localhost:7001` or `http://$IP_ADDRESS:7001`.

# Summary

Write a summary.
