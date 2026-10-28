<picture>
  <source media="(prefers-color-scheme: dark)" srcset="images/ok3d-logo-dark.svg">
  <img src="images/ok3d-logo.svg" alt="ok3d logo: an amber pulse line above a row of device tiles" width="88">
</picture>

# ok3d

A network operations center for your home: ok3d watches every device on your network and
tells you, on your phone or by email, when something breaks, before anyone in the house
tells you. It runs on one Linux server, in a small Kubernetes cluster (k3d) that it builds
and looks after itself.

- **Every device, checked.** List your devices once, in `devices.yaml`: your router,
  switches, access points, NAS, servers, printer. ok3d pings each one and checks its pages
  and ports every 30 seconds.
- **Alerts that reach you.** ntfy on your phone, email, or both, with a runbook for every
  alert. A dead man's switch tells you when ok3d itself stops. When a device is down, you hear
  about the device, not about each of its checks.
- **UniFi, in detail.** With a view-only API key, ok3d reads your UniFi controller: each
  device's load, ports, clients, and the internet link's traffic, with UniFi's own dashboards.
- **Your computers.** Disks filling up, memory running low, a failed RAID disk, from
  node_exporter on each computer.
- **Pages that are yours.** Grafana, Prometheus, and Alertmanager over HTTPS, at names under
  your own domain, with a certificate authority of ok3d's own that you trust once on each
  device. Nothing is sent anywhere you didn't set up, and nothing else in the cluster is
  reachable from your network.
- **Data that lasts.** History, settings, and the certificate authority live in a folder on
  the server, so upgrading means making the cluster again, and it picks up where it left off.

ok3d is being built release by release: [docs/roadmap.md](docs/roadmap.md) says where it
stands, and [PLAN.md](PLAN.md) says where it's going, with the reasons. Coming next: a
Dashboard to set it all up from a web page, logs and syslog, a NOC board, one sign-in for
every page, and AI agents that explain what went wrong.

## What you need

- A Linux server with about 8 GB of memory free (more once agents arrive in 0.9), Docker,
  [k3d](https://k3d.io) 5.9 or newer, [Helm](https://helm.sh), `kubectl`, and `openssl`.
- A folder for ok3d's data, on a filesystem of its own if you can.
- A way to add a name to your local DNS: most routers can, and so can Pi-hole.

## Try it

On the server:

```sh
git clone https://github.com/southsidedean/observability-k3d.git ok3d && cd ok3d
cp settings.example.yaml settings.yaml        # edit it: at least the data folder
sudo install -d -o "$USER" -m 0755 /srv/ok3d  # the data folder, owned by you
./ok3d check                                  # is this server ready?
./ok3d demo up                                # optional: a simulated network to watch
cp devices.demo.yaml devices.yaml             # watch the simulated network for now
./ok3d apply                                  # make the cluster and deploy everything
```

`./ok3d apply` ends by printing the pages' addresses. Then:

1. [Open the pages](docs/certificate.md): point the names at the server, and trust ok3d's
   certificate authority on your devices.
2. [Get alerts](docs/alerts.md): ntfy, email, and the dead man's switch.
3. [List your own devices](docs/devices.md), and switch UniFi on if you have it.

`./ok3d test-alert` checks that alerts reach you. `./ok3d delete --yes` deletes the cluster
and keeps your data; `./ok3d apply` brings it back.

## The docs

| Page | What it covers |
|---|---|
| [How ok3d fits together](docs/architecture.md) | The pieces, and how you set it up |
| [Opening ok3d's pages](docs/certificate.md) | Local DNS, and trusting the certificate authority |
| [Your devices](docs/devices.md) | `devices.yaml`, the checks, node_exporter, UniFi |
| [Alerts](docs/alerts.md) | ntfy, email, the dead man's switch, silences |
| [Runbooks](docs/runbooks/README.md) | What each alert means and what to check |
| [The simulated network](docs/demo.md) | Trying ok3d without a network of your own |
| [Upgrading](docs/upgrading.md) | New releases, and moving from the old stack |
| [Roadmap](docs/roadmap.md) | Where ok3d is, release by release |

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) covers setting up, the checks every change passes, and
how releases happen. Security problems go to a private report:
[SECURITY.md](SECURITY.md) says how.

ok3d is licensed under the [AGPL-3.0](LICENSE).
