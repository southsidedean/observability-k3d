# Upgrading

## To a new release

Everything worth keeping stays in the data root, so a new release picks up where the old one
left off. Before you move, read the release's notes in [CHANGELOG.md](../CHANGELOG.md),
especially anything under "Upgrading".

### From the Dashboard (from 0.5.1)

On Home, press **Look for a new release**, read the notes it links to, then **Upgrade to** the
release and **Upgrade now**. [The Dashboard's guide](dashboard.md#upgrading) walks through it.

### With a command (from 0.5.1)

On the server, as yourself:

```sh
cd ~/ok3d
./ok3d upgrade           # is a newer release out?
./ok3d upgrade v0.5.2    # move to it (it asks first; --yes skips the question)
```

Either way, the upgrade:

1. Fetches the release's tag, and checks that it's signed with ok3d's release key (the keys
   in `deploy/release-signers`, as your copy has them). It stops if it isn't.
2. Copies your `settings.yaml`, `devices.yaml`, and `.env` to
   `local/backups/before-<release>-<time>/` in the ok3d folder.
3. Moves the ok3d folder to the release and runs its `./ok3d check`, then its `./ok3d install`,
   which brings the helper and the Dashboard up to the release. If either fails, it moves
   back and stops (after a failed install, it installs the old helper and Dashboard again):
   nothing else changed. Read what the check said, and the release's Upgrading notes, then
   try again.
4. Deletes the cluster, and backs up the certificate authority (`certs/`), Grafana's database
   (`grafana/`), and Alertmanager's silences (`alertmanager/`) while nothing is writing to
   them, to `backups/before-<release>-<time>.tar.gz` in the data root. The last three are
   kept. Prometheus's history is left out, since it's large; the new cluster picks it up as
   it is.
5. Makes the cluster again with `./ok3d apply`. The new cluster downloads its images again,
   so this can take as long as your first Apply did. ok3d's pages are down until it's done.

It moves only forward, one upgrade at a time, and needs Linux with systemd, like the helper.
The ok3d folder mustn't have changes of yours to ok3d's own files (your settings are safe:
they're not ok3d's), and it waits for anything the helper is doing for the Dashboard (an
Apply, say) to finish first.

### If an upgrade stops partway

The Dashboard's Home, or what `./ok3d upgrade` printed, says which step it stopped at.

- **The check or the install**: ok3d is back on the release you had, and the cluster wasn't
  touched. Fix what the check said, then upgrade again.
- **Deleting the cluster, the backup, or Apply**: the ok3d folder, the helper, and the
  Dashboard are on the new release. Fix what Apply said, then **Check** and **Apply** on the
  Dashboard, or `./ok3d apply` on the server.
- **The server restarted partway**: Home says the upgrade stopped, and at which step. If it
  stopped before "Moving to", nothing changed: upgrade again. If it stopped later, the ok3d
  folder is already on the new release, so finish by hand on the server:

  ```sh
  cd ~/ok3d
  ./ok3d install       # the new release's helper and Dashboard, if that step hadn't finished
  ./ok3d apply         # makes the cluster again with the new release
  ```

To go back to the release you had instead, put the backups back where they were and make
the cluster again from it:

```sh
cd ~/ok3d
git switch --detach v0.5.1                   # the release you had
cp local/backups/before-v0.5.2-<time>/* .    # your settings, devices, and .env from before
cp local/backups/before-v0.5.2-<time>/.env .
./ok3d install
./ok3d delete --yes
tar -C /srv/ok3d -xzf /srv/ok3d/backups/before-v0.5.2-<time>.tar.gz   # your data root
./ok3d apply
```

Your settings go back to how they were, in case you changed them for the new release, and
Grafana's database goes back to how it was before the upgrade, which matters if the new
release's Grafana changed it.

### To 0.5.1, from 0.5.0 or 0.4

Those releases don't have `./ok3d upgrade`, so run the installer again, on the server, as
yourself. If you cloned ok3d somewhere other than `~/ok3d`, put `OK3D_DIR=/path/to/ok3d`
before `sh`, or it makes a fresh copy there:

```sh
curl -fsSL https://raw.githubusercontent.com/southsidedean/observability-k3d/main/install.sh | sh
```

It brings `~/ok3d` to the latest release, keeps your settings, devices, `.env`, and the
certificate authority, and starts the new release's Dashboard. From 0.4, this is also what
first sets up the Dashboard. It stops if you changed ok3d's own files. Back up `grafana/` and
`certs/` in the data root first. Then, on the Dashboard, **Check**, then **Apply**, which
brings the cluster up to date with the new release.

Either way, Prometheus's history, Alertmanager's silences, Grafana's database, and the
certificate authority come through unchanged, so your devices keep trusting the pages.

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
