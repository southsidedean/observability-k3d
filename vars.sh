#!/bin/bash
# vars.sh
# Environment variables for the sandbox
#
# Tom Dean
# Last edit: 9/12/2025
#
# Set variables here and then execute or source script
# Do this before executing any sandbox scripts

export CLUSTER_NAME=observability-cluster
export KUBECTX_NAME=observability-cluster
export CLUSTER_NETWORK=observability-network
export PERSISTENT_DATA_PATH="/media/content/observability"
export MONITORING_NAMESPACE=monitoring
export KAGENT_NAMESPACE=kagent
export KAGENT_VERSION=0.6.11
export OPENAI_API_KEY=""
export KGATEWAY_VERSION="2.1.0-main"
export KGATEWAY_NAMESPACE=kgateway-system
export GATEWAY_API_VERSION="v1.3.0"
export OPENAI_API_KEY=""
export GRAFANA_ADMIN_PASSWORD="prom-operator"
export K3S_VERSION="rancher/k3s:v1.31.7-k3s1"

# --- UniFi Poller Settings ---
export UNIFI_CONTROLLER_URL="https://unifi.yourdomain.com" # CHANGE THIS to your UniFi controller URL
export UNIFI_CONTROLLER_USER="unifipoller"                 # CHANGE THIS to a read-only user on your controller
export UNIFI_CONTROLLER_PASS="your_password_here"          # CHANGE THIS to the user's password

export SYSLOG_PORT=1514
