# Homelab Observability on k3d + kgateway

A complete, GitOps-friendly observability stack for a k3d (k3s-in-Docker) Kubernetes cluster, fronted by **kgateway**.

Includes:
- **kube-prometheus-stack** (Prometheus, Alertmanager, Grafana)
- **Loki + Promtail** with a **syslog receiver** (TCP 30114 / UDP 30115)
- **Blackbox Exporter** (ICMP + HTTP probes)
- **Grafana** provisioning: datasources, dashboards, alert rules, contact points, notification policies
- **Security dashboard** + metrics & log annotations + Active Alerts dashboard
- **UniFi integration**: **Unpoller** (metrics) + UniFi syslog ingestion
- Persistence under **`/media/content/observability-k3d`**
- **kgateway** Gateway + HTTPRoutes for Grafana/Prometheus/Alertmanager/Loki

## 0) Prereqs
```bash
sudo mkdir -p /media/content/observability-k3d/{grafana,prometheus,loki,unpoller,grafana/dashboards}
sudo chown -R $USER:$USER /media/content/observability-k3d
```

## 1) Create the k3d cluster
```bash
./scripts/create-k3d.sh
```

## 2) Deploy the stack (Helm-first, then Kustomize)
```bash
./scripts/helm-install.sh
kubectl apply -k monitoring/
kubectl apply -f ingress/kgateway.yaml
```

## 3) rsyslog → Promtail (Loki)
Set your servers (and UniFi gear) to forward to `<HOST_IP>:30114` (TCP). See `extras/rsyslog-forward-example.conf`.

## 4) UniFi (Unpoller)
```bash
./extras/create-unifi-secret.sh unifipoller <YOUR_PASSWORD>
# edit monitoring/unifi/deployment.yaml → UP_UNIFI_DEFAULT_URL
kubectl apply -k monitoring/
```

## Passwords & URLs
- Grafana admin: `kubectl get secret kube-prometheus-grafana -n monitoring -o jsonpath='{.data.admin-password}' | base64 -d; echo`
- Grafana → http://grafana.local, Prometheus → http://prometheus.local, Alertmanager → http://alertmanager.local, Loki API → http://loki.local

MIT
