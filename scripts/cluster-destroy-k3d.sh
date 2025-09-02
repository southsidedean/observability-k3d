#!/bin/bash
# cluster-destroy-k3d.sh
# Automates cluster deletion and cleans up the kubectl contexts
# Tom Dean
# Last edit: 4/25/2025

# Set environment variables

source vars.sh

# Remove the k3d cluster

for cluster in `seq -f %02g 1 $NUM_CLUSTERS`
do
clustername=$CLUSTER_NAME_PREFIX$cluster
k3d cluster delete $clustername
done

k3d cluster list

# Remove the kubectl context

for kubectx in `seq -f %02g 1 $NUM_CLUSTERS`
do
kubectxname=$KUBECTX_NAME_PREFIX$kubectx
kubectx -d $kubectxname
done

kubectx

echo "Clusters deleted!"

exit 0
