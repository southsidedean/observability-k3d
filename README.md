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
stands, and [PLAN.md](PLAN.md) says where it's going, with the reasons. From 0.5 you set it
up on a web page, the Dashboard. Coming next: logs and syslog, a NOC board, one sign-in for
every page, and AI agents that explain what went wrong.

## What you need

- A Linux server with systemd and about 8 GB of memory free (more once agents arrive in 0.9),
  [Docker](https://docs.docker.com/engine/install/), [k3d](https://k3d.io) 5.9 or newer,
  [Helm](https://helm.sh), [`kubectl`](https://kubernetes.io/docs/tasks/tools/), `git`,
  `curl`, `openssl`, and Python 3.
- A folder for ok3d's data, on a filesystem of its own if you can.
- A way to add a name to your local DNS: most routers can, and so can Pi-hole.

## Install

**With an AI assistant.** If you use one that can run commands on your server, such as Claude
Code, open it in a terminal on the server, as yourself, and paste this in. It works out
what's missing, gives you each `sudo` command to run yourself, runs the installer, and stops
once the Dashboard is running. It's told never to read your passwords or keys.
[Installing with an AI assistant](docs/install-with-ai.md) says what it does, and what to
watch for.

```text
Install ok3d on this Linux server for me, from https://github.com/southsidedean/observability-k3d.
Use its latest release (the one GitHub marks Latest), and read docs/install-with-ai.md at
that release's tag. Follow its rules and steps, in order, as written. Never run sudo
yourself: show me each sudo command and I'll run it in my own terminal. Never read, print,
or ask me for a password, API key, or other secret. If a step fails, show me the exact
error and stop. Stop when the Dashboard is running, and tell me how to open it.
```

**By hand.** On the server, as yourself (not root), with what's above installed:

```sh
sudo install -d -o "$USER" -m 0755 /srv/ok3d   # the data folder, owned by you
curl -fsSL https://raw.githubusercontent.com/southsidedean/observability-k3d/main/install.sh | sh
```

Either way, the installer puts ok3d in `~/ok3d` and starts the Dashboard, a web page where
you choose what ok3d watches and where alerts go, then Check and Apply. It prints the
Dashboard's address. [Setting up from the Dashboard](docs/dashboard.md) goes through each
page, and [Opening ok3d's pages](docs/certificate.md) says how to reach it from your
computer.

**With commands instead.** Everything the Dashboard does is an `./ok3d` command too:

```sh
git clone https://github.com/southsidedean/observability-k3d.git ok3d && cd ok3d
cp settings.example.yaml settings.yaml        # edit it: at least the data folder
sudo install -d -o "$USER" -m 0755 /srv/ok3d  # the data folder, owned by you
./ok3d check                                  # is this server ready?
./ok3d demo up                                # optional: a simulated network to watch
cp devices.demo.yaml devices.yaml             # watch the simulated network for now
./ok3d apply                                  # make the cluster and deploy everything
```

`./ok3d apply` ends by printing the pages' addresses. Then
[open the pages](docs/certificate.md), [get alerts](docs/alerts.md), and
[list your own devices](docs/devices.md). `./ok3d test-alert` checks that alerts reach you.
`./ok3d delete --yes` deletes the cluster and keeps your data; `./ok3d apply` brings it back.
`./ok3d upgrade` says whether a newer release is out, and moves to it ([upgrading](docs/upgrading.md)).

## The docs

| Page | What it covers |
|---|---|
| [How ok3d fits together](docs/architecture.md) | The pieces, and how you set it up |
| [Setting up from the Dashboard](docs/dashboard.md) | The installer, and each of the Dashboard's pages (from 0.5) |
| [Installing with an AI assistant](docs/install-with-ai.md) | The prompt, and the steps it follows |
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
