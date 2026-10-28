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
gone from 0.4. ok3d starts fresh: a new data folder, its own certificate authority, its own
admin login, and its own dashboards.

### 1. Stop the old cluster, if it's still running

```sh
k3d cluster list
k3d cluster delete observability-cluster   # CLUSTER_NAME from your old vars.sh
```

Deleting it leaves its data folder (`PERSISTENT_DATA_PATH` in `vars.sh`) as it was.

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

### 3. Apply

```sh
./ok3d check
./ok3d apply
```

Keep the old data folder for a week or two, in case you want something from it, then delete
it.

### Keeping old history (optional, untested)

The old history is rarely worth keeping: its labels don't match what ok3d collects, so
ok3d's dashboards and alerts won't show it. If you want it anyway, copy it into the new data
root before the first `./ok3d apply`. Nobody has tried this on a real old stack's data yet,
so keep the old folder until it works.

- **Prometheus:** only early versions of the old stack kept history in the data folder, in
  `prometheus/prometheus-db/`. v0.2.0 kept it inside the cluster, so it went when the cluster
  did. If the folder is there:

  ```sh
  mkdir -p /srv/ok3d/prometheus
  sudo cp -a /old/data/prometheus/prometheus-db/. /srv/ok3d/prometheus/
  sudo chown -R "$USER": /srv/ok3d/prometheus
  ```

- **Grafana:** if you made dashboards by hand, it's simpler to export each one (its Share
  menu, Export, Save to file) and import it into ok3d's Grafana. To keep the whole database
  instead, copy `grafana/grafana.db` into the new data root's `grafana/` folder, make it
  yours (`sudo chown "$USER": grafana.db`, since the old Grafana ran as user 472), and after
  applying, reset the admin password, because Grafana only takes ok3d's when it makes a new
  database:

  ```sh
  kubectl --context k3d-ok3d -n monitoring exec deploy/ok3d-grafana -c grafana -- \
    grafana cli admin reset-admin-password "$(cat /srv/ok3d/admin-password)"
  ```

- **Logs:** the old Loki's data can't come across: ok3d's Loki, from 0.6, uses a newer
  storage format.
