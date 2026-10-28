# Upgrading

## To a new release

ok3d's cluster is made again on every upgrade, and everything worth keeping stays in the
data root, so a new cluster picks up where the old one left off.

1. Read the release's notes in [CHANGELOG.md](../CHANGELOG.md), especially anything under
   "Upgrading".
2. Back up the data root's small, precious parts: `grafana/`, `certs/`, and your
   `settings.yaml`, `devices.yaml`, and `.env`. (From 0.7, `./ok3d backup` does this.)
3. Move to the release and make the cluster again:

   ```sh
   git fetch --tags && git switch --detach v0.4.0   # the release you're moving to
   ./ok3d check
   ./ok3d delete --yes
   ./ok3d apply
   ```

Prometheus's history, Alertmanager's silences, Grafana's database, and the certificate
authority come through unchanged, so your devices keep trusting the pages.

## From the old stack (v0.2.0 and before)

The old stack (`scripts/cluster-setup-k3d-observability-everything.sh` and `vars.sh`) is
gone from 0.4. Moving to ok3d takes a few steps, because the two keep their data in
different layouts, and ok3d makes its own certificate authority and admin login.

### 1. Stop the old cluster

```sh
k3d cluster delete observability-cluster   # CLUSTER_NAME from your old vars.sh
```

Its data folder (`PERSISTENT_DATA_PATH` in `vars.sh`) stays as it was. Prometheus's history
goes with the cluster, unless it's in that folder (step 3 says how to tell).

### 2. Make ok3d's settings

| Old `vars.sh` | ok3d |
|---|---|
| `PERSISTENT_DATA_PATH` | `host.dataRoot` in `settings.yaml`: use a new, empty folder, not the old one |
| `UNIFI_CONTROLLER_URL` | `unifi.url` in `settings.yaml`, with `modules.unifi: true` |
| `UNIFI_CONTROLLER_USER`, `UNIFI_CONTROLLER_PASS` | an API key from a view-only admin, as `UNIFI_API_KEY` in `.env` ([how](devices.md#unifi)) |
| `GRAFANA_ADMIN_PASSWORD` | `OK3D_ADMIN_PASSWORD` in `.env`, or leave it empty and ok3d makes one |
| `OPENAI_API_KEY` | nothing yet: agents arrive in 0.9, through Claude |
| The node_exporter targets in `additional-scrape-configs.yaml` | each computer in `devices.yaml`, with `metrics: ["9100"]` ([how](devices.md)) |

The pages move too: from `http://<server>:7001/grafana` to
`https://grafana.noc.home.arpa:8443/` and its neighbours ([opening the pages](certificate.md)).
Syslog on port 30114 comes back in 0.6.

### 3. Bring Prometheus's history across (optional)

Early versions of the old stack kept Prometheus's history in the data folder, in
`prometheus/prometheus-db/`. v0.2.0 kept it inside the cluster instead, so if that folder
isn't there, the history went with the cluster and there's nothing to bring.

If it's there, copy it into `prometheus/` under ok3d's data root before the first
`./ok3d apply`, and make it yours:

```sh
mkdir -p /srv/ok3d/prometheus
sudo cp -a /old/data/prometheus/prometheus-db/. /srv/ok3d/prometheus/
sudo chown -R "$USER": /srv/ok3d/prometheus
```

Prometheus reads the old history as it is, and keeps what fits in `metrics.retention`. Old
series keep their old labels, so the new dashboards and alerts start from what ok3d
collects.

### 4. Grafana: start fresh

ok3d brings its own dashboards, so starting Grafana with an empty database is simplest. If
you edited dashboards in the old Grafana, export them first (each dashboard's Share menu,
Export, Save to file) and import them into the new one.

To keep the old database instead, copy `grafana/grafana.db` into the data root's `grafana/`
folder before the first apply, make it yours (the old Grafana ran as user 472, so
`sudo chown "$USER": grafana.db`), and then reset the admin password, since
Grafana reads ok3d's only when it makes a new database:

```sh
kubectl --context k3d-ok3d -n monitoring exec deploy/ok3d-grafana -c grafana -- \
  grafana cli admin reset-admin-password "$(cat /srv/ok3d/admin-password)"
```

### 5. Logs

The old Loki's data doesn't carry over: its storage format is older than the one ok3d's
Loki uses from 0.6. Its logs stay in the old folder if you want them.

### 6. Apply

```sh
./ok3d check
./ok3d apply
```

This guide hasn't yet been tried on a real old stack's data: back up the old data folder
first, and keep it until ok3d is working.
