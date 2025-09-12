#!/bin/bash
# cluster-setup-k3d-naked.sh
# Automates k3d cluster creation
# Tom Dean
# Last edit: 9/12/2025

# Set environment variables

source vars.sh

# Delete existing k3d cluster

k3d cluster delete $CLUSTER_NAME

# Create the k3d cluster

k3d cluster create $CLUSTER_NAME -c cluster-k3d/k3d-cluster.yaml --port 7001:80@loadbalancer --port 7401:443@loadbalancer --api-port 0.0.0.0:7601
k3d cluster list

# Configure the kubectl context

kubectx -d $KUBECTX_NAME
kubectx $KUBECTX_NAME=k3d-$CLUSTER_NAME
kubectx $KUBECTX_NAME
kubectx

exit 0
