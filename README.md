# Homelab Observability on k3d + kgateway

A complete, GitOps-friendly observability stack for a k3d (k3s-in-Docker) Kubernetes cluster, fronted by **kgateway**.
It includes:

- **kube-prometheus-stack** (Prometheus, Alertmanager, Grafana, exporters)
- **Loki + Promtail** with a **syslog receiver** (TCP 30114 / UDP 30115)
- **Blackbox Exporter** (ICMP + HTTP probes)
- **Grafana** pre-provisioned: **datasources, dashboards, alert rules, contact points, notification policies**
- **Security dashboard** + **metrics & log annotations** + **Active Alerts** dashboard
- **UniFi integration**: **Unpoller** (metrics) + UniFi **syslog** collection + optional auto-provisioned **official Unpoller dashboards**
- Persistent data on the k3d host under **`/media/content/observability-k3d`**
- **kgateway** Gateway + HTTPRoutes exposing Grafana, Prometheus, Alertmanager, Loki

> Default timezone: America/Chicago. Adjust anything to your needs.

---

## 0) Prereqs

- Docker + k3d
- kubectl + Helm v3
- kgateway installed (GatewayClass name: `kgateway`)
- Host path: **`/media/content/observability-k3d`** (created on the k3d host)
```bash
sudo mkdir -p /media/content/observability-k3d/{grafana,prometheus,loki,unpoller,grafana/dashboards}
sudo chown -R $USER:$USER /media/content/observability-k3d
```

---

## 1) Create the k3d cluster (with hostPath mount)

```bash
./scripts/create-k3d.sh
```

- Cluster `homelab`; NodePorts 30000‑30100 → host
- API on `localhost:6445`
- Host mount `/media/content/observability-k3d` → same path inside nodes

> If you already have a cluster, mount the path using `k3d cluster create --volume /media/content/observability-k3d:/media/content/observability-k3d@all` or equivalent.

---

## 2) Deploy the stack

```bash
kubectl create ns monitoring
kubectl apply -k monitoring/
```

This installs:
- kube-prometheus-stack (Prometheus, Grafana, Alertmanager)
- Loki + Promtail syslog receiver (NodePorts 30114 TCP / 30115 UDP)
- Blackbox exporter + probes
- Grafana provisioning (datasources, dashboards, alerts, contact points)
- PV/PVCs (hostPath) for Prometheus/Grafana/Loki
- **Unpoller** (UniFi metrics) + `ServiceMonitor`

---

## 3) Expose UIs via kgateway

After installing kgateway:

```bash
kubectl apply -f ingress/kgateway.yaml
```

Add entries to your workstation’s `/etc/hosts` or internal DNS (replace `<HOST_IP>`):

```
<HOST_IP> grafana.local prometheus.local alertmanager.local loki.local
```

Then browse:
- Grafana → `http://grafana.local` (admin password below)
- Prometheus → `http://prometheus.local`
- Alertmanager → `http://alertmanager.local`
- Loki API → `http://loki.local`

---

## 4) Grafana admin password

```bash
kubectl get secret kube-prometheus-grafana -n monitoring -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

Provisioned datasources:
- **Prometheus** → `http://prometheus-operated.monitoring.svc:9090`
- **Loki** → `http://loki.monitoring.svc:3100`

---

## 5) rsyslog → Promtail (Loki)

On each Ubuntu/Linux node (except the central one if it’s already forwarding), create `/etc/rsyslog.d/60-central-syslog.conf`:

```conf
*.* action(
  type="omfwd"
  target="<HOST_IP>"
  port="30114"
  protocol="tcp"
  action.resumeRetryCount="-1"
  queue.type="linkedList"
  queue.size="10000"
)
```
Then:
```bash
sudo systemctl restart rsyslog
```

Promtail listens on NodePorts:
- **TCP 30114**
- **UDP 30115**

---

## 6) UniFi Metrics & Dashboards

### Unpoller (metrics from UniFi controller)
1. Create the credentials Secret (read‑only admin on the controller):
```bash
./extras/create-unifi-secret.sh unifipoller <YOUR_PASSWORD>
```
2. Edit `monitoring/unifi/deployment.yaml` and set your controller URL:
```yaml
UP_UNIFI_DEFAULT_URL: "https://<controller-host-or-ip>:8443"   # UniFiOS may use 443
UP_UNIFI_DEFAULT_VERIFY_SSL: "false"                           # if self-signed
```
3. Apply (or re-apply) the overlay:
```bash
kubectl apply -k monitoring/
```

### UniFi dashboards (optional auto-provision)
You can import dashboards manually (Grafana IDs: **11310, 11311, 11312, 11313, 11314, 11315, 23027**) or run the provided add-on in `integrations/unifi/` to auto-fetch and file‑provision them into Grafana from a PV at `/media/content/observability-k3d/grafana/dashboards/unifi`.

> If you want me to wire the auto-fetch Job directly into this overlay, let me know and I’ll embed it here; otherwise use the add-on zip I provided.

### UniFi logs
In the UniFi Network App, set **Syslog Host** to your k3d host’s IP, TCP 30114 (or UDP 30115). Logs appear in Loki with labels `host` (device) and `app`.

---

## 7) Alerts & Routing

- **Prometheus alerts**: NodeDown, HighCPU (critical), HighMemory/Disk (warning), Security (SSH brute force, sudo failures).  
- **Loki/Grafana alerts**: SSH brute force & sudo failures via provisioned Grafana alerts.  
- **Contact points & policies** (Grafana provisioned):
  - `severity=critical` → Slack + Email
  - `severity=warning` → Slack
  - Catch-all → Slack

Edit Slack webhook / email in `monitoring/grafana/alerting.yaml` and re-apply.

---

## 8) Blackbox probes

- Gateway ICMP ping (`192.168.1.1` by default)
- Public DNS (8.8.8.8, 1.1.1.1)
- Websites (cloudflare.com, grafana.com)

Tune targets under `monitoring/probes/`.

---

## 9) Security & navigation dashboards

- **Security Dashboard** (SSH/sudo failures, security alerts)
- **Active Alerts** dashboard
- Cross‑links between **System Metrics**, **Logs Overview**, and **Active Alerts**
- **Annotations** on CPU/Memory graphs (Prometheus alerts + Loki log events)

---

## 10) Clean up

```bash
./scripts/destroy.sh
```

---

## FAQ

**Where is persistence stored?**  
All persistent data lives on the k3d host under `/media/content/observability-k3d/{prometheus,grafana,loki,unpoller,grafana/dashboards}` via hostPath PVs.

**Why `prometheus-operated` Service?**  
It’s stable and provided by the Prometheus Operator; easier than chart-named services.

**TLS?**  
kgateway supports HTTPS/TLS; add a TLS listener and certificates if desired.

**Can I change NodePorts for syslog?**  
Yes: `monitoring/loki-stack-values.yaml` → `extraPorts.syslog-{tcp,udp}.service.nodePort`.

MIT License.
