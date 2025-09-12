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
export KAGENT_NAMESPACE=kagent
export KAGENT_VERSION=0.6.11
export OPENAI_API_KEY=""
export KGATEWAY_VERSION="2.1.0-main"
export KGATEWAY_NAMESPACE=kgateway-system
export GATEWAY_API_VERSION="v1.3.0"
export OPENAI_API_KEY=""
export K3S_VERSION="rancher/k3s:v1.31.7-k3s1"
