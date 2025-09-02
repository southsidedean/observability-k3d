# observability-k3d

## Tom Dean
## Last edit: 9/2/25

## *INITIAL DRAFT - UNDER DEVELOPMENT*

## Introduction

Introduction.

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

## About the Observability Cluster

Introduction

All the Helm `values` files and other YAML manifests live in the `manifest` directory:

```bash
manifests
├── grafana-ingress.yaml
├── grafana-values.yaml
├── http-listener.yaml
├── kagent-httproute.yaml
├── kagent-values.yaml
├── monitoring
│   ├── alerts
│   │   ├── kustomization.yaml
│   │   └── prometheus-rules.yaml
│   ├── kustomization.yaml
│   ├── loki-stack-values.yaml
│   └── probes
│       ├── kustomization.yaml
│       ├── probe-dns.yaml
│       ├── probe-gateway.yaml
│       └── probe-websites.yaml
└── registries.yaml
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
