#!/bin/bash
# cluster-destroy-k3d.sh
# Automates cluster deletion and cleans up the kubectl contexts
# Tom Dean
# Last edit: 9/12/2025

# Set environment variables

source vars.sh

# Remove the k3d cluster

k3d cluster delete $CLUSTER_NAME
k3d cluster list

# Remove the kubectl context

kubectx -d $KUBECTX_NAME
kubectx

echo "Cluster deleted!"

exit 0
