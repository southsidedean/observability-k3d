#!/bin/bash
# cluster-setupt-observability-k3d.sh
# Complete k3d cluster + observability + alerting stack
# Includes kgateway and kagent
# Tom Dean
# Last edit: 9/4/2025

# Load environment variables
source vars.sh

# --- DELETE EXISTING CLUSTERS ---
for cluster in $(seq -f %02g 1 $NUM_CLUSTERS); do
  clustername=$CLUSTER_NAME_PREFIX$cluster
  k3d cluster delete $clustername
done

# --- CREATE K3D CLUSTERS ---
for cluster in $(seq -f %02g 1 $NUM_CLUSTERS); do
  clustername=$CLUSTER_NAME_PREFIX$cluster
  k3d cluster create $clustername -c cluster-k3d/k3d-cluster.yaml \
    --port 70${cluster}:80@loadbalancer \
    --port 74${cluster}:443@loadbalancer \
    --api-port 0.0.0.0:76${cluster}
done

k3d cluster list

# --- CONFIGURE KUBECTX ---
for kubectx in $(seq -f %02g 1 $NUM_CLUSTERS); do
  kubectxname=$KUBECTX_NAME_PREFIX$kubectx
  clustername=$CLUSTER_NAME_PREFIX$kubectx
  kubectx -d $kubectxname
  kubectx $kubectxname=k3d-$clustername
done
kubectx ${KUBECTX_NAME_PREFIX}01
kubectx

# --- INSTALL KAGENT ---
curl https://raw.githubusercontent.com/kagent-dev/kagent/refs/heads/main/scripts/get-kagent | bash
for cluster in $(seq -f %02g 1 $NUM_CLUSTERS); do
  kubectxname=$KUBECTX_NAME_PREFIX$cluster
  helm install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
    --namespace $KAGENT_NAMESPACE \
    --create-namespace \
    --kube-context $kubectxname
  helm install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
    --namespace $KAGENT_NAMESPACE \
    --set providers.openAI.apiKey=$OPENAI_API_KEY \
    --kube-context $kubectxname
  watch -n 1 kubectl get all -n $KAGENT_NAMESPACE --context $kubectxname
done

# --- DEPLOY MOVIES APP ---
for cluster in $(seq -f %02g 1 $NUM_CLUSTERS); do
  kubectxname=$KUBECTX_NAME_PREFIX$cluster
  kubectl apply -k movies --context $kubectxname
done

# --- INSTALL KGATEWAY ---
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/${GATEWAY_API_VERSION}/standard-install.yaml
helm upgrade -i --create-namespace --namespace $KGATEWAY_NAMESPACE --version v${KGATEWAY_VERSION} \
  kgateway-crds oci://cr.kgateway.dev/kgateway-dev/charts/kgateway-crds
helm upgrade -i --namespace $KGATEWAY_NAMESPACE --version v${KGATEWAY_VERSION} \
  kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway
kubectl apply -f manifests/http-listener.yaml
kubectl apply -f manifests/kagent-httproute.yaml
kubectl get gateways -A
kubectl get httproute -A

# --- OBSERVABILITY STACK + ALERTMANAGER ---
for cluster in $(seq -f %02g 1 $NUM_CLUSTERS); do
  kubectxname=$KUBECTX_NAME_PREFIX$cluster
  echo "Deploying observability stack to $kubectxname"

  # Namespace
  kubectl create namespace monitoring --context $kubectxname --dry-run=client -o yaml | kubectl apply -f -

  # Persistent host directories
  mkdir -p /media/content/observability-k3d/{grafana,loki,prometheus,promtail-positions,GeoLite2-City.mmdb}
  if [ ! -f /media/content/observability-k3d/GeoLite2-City.mmdb ]; then
    echo "GeoLite2-City.mmdb not found! Download it from MaxMind and place it in /media/content/observability-k3d/"
    exit 1
  fi

  # Grafana admin secret
  kubectl create secret generic grafana-admin \
    --from-literal=admin-user=$GRAFANA_ADMIN_USER \
    --from-literal=admin-password=$GRAFANA_ADMIN_PASSWORD \
    -n monitoring \
    --context $kubectxname \
    --dry-run=client -o yaml | kubectl apply -f -

  # Apply observability stack manifests
  kubectl apply -k observability-k3d --context $kubectxname

  # --- ALERTMANAGER DEPLOYMENT ---
  kubectl apply -f observability-k3d/prometheus/alertmanager-deployment.yaml --context $kubectxname
  kubectl apply -f observability-k3d/prometheus/alertmanager-service.yaml --context $kubectxname
  kubectl apply -f observability-k3d/prometheus/alertmanager-config.yaml --context $kubectxname

  # Wait for Grafana pod
  echo "Waiting for Grafana pod..."
  kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=grafana -n monitoring --timeout=180s --context $kubectxname

  # Import dashboards
  for dashboard in observability-k3d/grafana/dashboards/*.json; do
    echo "Importing $dashboard..."
    POD=$(kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana --context $kubectxname -o jsonpath="{.items[0].metadata.name}")
    kubectl cp $dashboard monitoring/$POD:/tmp/dashboard.json --context $kubectxname
    kubectl exec -n monitoring $POD --context $kubectxname -- grafana-cli dashboards import /tmp/dashboard.json
  done

  # Wait for all monitoring pods
  echo "Waiting for all monitoring pods..."
  kubectl wait --for=condition=Ready pods --all -n monitoring --timeout=300s --context $kubectxname
done

echo "✅ All clusters, apps, KGW, KAgent, observability stack, and alerting deployed successfully."
exit 0