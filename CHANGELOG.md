# Changelog

## 0.5.0 (unreleased)

### Upgrading

- `settings.yaml` may hold only your own settings, and `devices.yaml` only `devices`.
  `./ok3d check` now refuses either one if it sets the chart's own sections
  (`kube-prometheus-stack`, `prometheus-blackbox-exporter`, `gateway`, `global`), which
  choose images and how pods run. Nothing in the docs ever asked for them;
  [chart/ok3d-files/README.md](chart/ok3d-files/README.md) has the list.
- A certificate authority made from 0.5 on can't vouch for any IP address, only for names
  under your domain. One you already have is kept as it is, so your devices keep trusting it;
  to get the new limit, move `certs/` aside and run `./ok3d apply`, then trust the new one.
- A device's address can't be a name inside the cluster (`.svc`, `.cluster.local`),
  `localhost`, or a loopback, link-local, or `0.x` address: ok3d watches your network, not
  itself.

### Changes

- The helper, which runs `./ok3d check` and `./ok3d apply` when the Dashboard asks. It's a
  small service on the server, running as you, and it refuses any request that isn't
  exactly one of those two. The Dashboard that uses it comes later in 0.5.
  [docs/helper-under-the-hood.md](docs/helper-under-the-hood.md) says how it works.
- The Dashboard's first part: its image, `ghcr.io/southsidedean/ok3d-dashboard`, for amd64 and
  arm64, and a first page behind a sign-in of its own, over HTTPS only. It shows ok3d's
  version and the helper's last answer; the pages for settings, devices, and Check and Apply
  come next. [docs/dashboard-under-the-hood.md](docs/dashboard-under-the-hood.md) says how
  it's built.
- The helper can now save `settings.yaml` and `devices.yaml` for the Dashboard, after
  `./ok3d validate` checks them, and set one line of `.env` at a time, never sending a value
  back. Settings from the Dashboard can't change where ok3d keeps its data, where it sends
  your keys, tokens, and passwords, or how far it's open to the outside, and the Dashboard
  can't set the admin password; you change those on the server. It keeps the last 10
  copies of each file in `local/backups/`.
- `./ok3d validate settings FILE` and `./ok3d validate devices FILE` check a file before it
  replaces yours, the way `./ok3d check` checks the ones in place.
- The installer: `curl -fsSL https://raw.githubusercontent.com/southsidedean/observability-k3d/main/install.sh | sh`
  checks out the newest release into `~/ok3d`, makes your first `settings.yaml`, and runs the
  new `./ok3d install`, which starts the helper as a service of yours and the Dashboard's
  container, issues the Dashboard's certificate, and prints its address
  (`https://dashboard.<domain>:8444`) and password. `cluster.ports.dashboard` sets its port.
- The Dashboard's pages: Home, with **Check** and **Apply** (which stays off until a Check
  finds no problems); **Settings** and **Devices**, to change and save your files; and
  **Keys**, to set the UniFi key, the ntfy topic and token, and the mail password, showing
  only whether each is set. Each sends one request at a time to the helper, and Home shows
  the answer.
- **Setup**, a page of ready-made setups (Basic NOC, and Network NOC with UniFi; logs and
  agents come in later releases) and a switch for each module and each place alerts go. It
  changes `settings.yaml` for you and saves it through the helper, like Settings. Home now
  lists what's left before ok3d can do its job (a key a part needs, somewhere for alerts to
  go, devices to watch) and, once an Apply has worked, What's next: DNS, trusting the
  certificate authority, Grafana, and a test alert.

### Fixes

- `.env.example` no longer says ok3d reads none of its secrets: 0.4 reads all but the agents'
  key.

## 0.4.0 (2026-10-28)

### Upgrading from the old stack

The old stack (`vars.sh`, `scripts/cluster-setup-k3d-observability-everything.sh`, and
`manifests/`) is gone. [docs/upgrading.md](docs/upgrading.md#from-the-old-stack-v020-and-before)
covers moving to ok3d: start fresh, with the settings that replace `vars.sh`.

### Changes

- A simulated network, for trying ok3d before pointing it at your own and for its tests and
  screenshots: `./ok3d demo up` starts a router, a switch, two access points, a NAS, a printer,
  and a fake UniFi controller that reports on them under unpoller's metric names, on addresses
  set aside for documentation. `./ok3d demo fail <device>` takes one down and
  `./ok3d demo fix <device>` brings it back. [docs/demo.md](docs/demo.md) has the details.
- Prometheus, with its history in the data root (30 days, 40 GB at most, both settings), so a
  rebuilt cluster keeps it. It runs as you, so the files are yours.
- `devices.yaml` lists the devices ok3d watches. Each device's checks (ping, http, https,
  tcp:<port>) run every 30 seconds, and its metrics ports are scraped. Ping works without
  root or extra privileges. [docs/devices.md](docs/devices.md) explains every field.
- With `modules.unifi` on, unpoller reads your UniFi controller with an API key from a
  view-only admin, kept in `.env` and given only to unpoller.
- Alerts reach you: on your phone through ntfy, by email, or both, and a dead man's switch
  hears from ok3d every minute, so you learn when ok3d itself stops.
  [docs/alerts.md](docs/alerts.md) has the steps. `./ok3d test-alert` sends a test alert.
- Twelve alerts for devices (down, a check failing, flapping, metrics gone, a certificate
  running out), UniFi (controller unreachable, busy, out of memory), and computers running
  node_exporter (disk filling, disk almost full, memory low, RAID degraded), each with a
  runbook in [docs/runbooks/](docs/runbooks/README.md). When a device is down, you hear
  about the device, not each of its checks.
- Every alert rule is tested with promtool, and a test holds each to metrics its exporter
  really serves, the check that would have caught the old stack's UniFi rules, which watched
  metrics unpoller never had.
- The front door: every page over HTTPS on one port, through agentgateway, at its own name
  under ok3d's domain: Grafana, Prometheus, Alertmanager, and the certificate authority to
  download. Nothing else in the cluster is reachable from your network.
  [docs/certificate.md](docs/certificate.md) says how to point the names at the server and
  trust the authority on each kind of device.
- Grafana, with ok3d's Devices dashboard and the UniFi dashboards, its database in the data
  root, and nothing sent anywhere (no usage reports or update checks).
- One admin login for Grafana and for the Prometheus and Alertmanager pages: the password is
  `OK3D_ADMIN_PASSWORD` in `.env`, or one ok3d makes and keeps in the data root.
- Inside the cluster, each of ok3d's namespaces turns away every connection it doesn't
  expect: the gateway may reach Grafana's, Prometheus's, and Alertmanager's pages and
  nothing else, and a pod outside ok3d can reach none of them directly.
- A new README, and [docs/upgrading.md](docs/upgrading.md) for new releases and for moving
  from the old stack.
- ok3d leaves out Kubernetes' own internal metrics, which k3s serves in bulk: an empty
  cluster now keeps about 5,000 series instead of about 100,000.

## 0.3.0 (2026-10-27)

The start of the rebuild as ok3d. This release sets up the project and its foundation: `ok3d`
makes the cluster and its own certificate authority, and keeps both across a rebuild. The
monitoring arrives in 0.4, which is the first release to run in place of the old stack.
[PLAN.md](PLAN.md) has the roadmap.

### Changes

- CI checks every pull request: lint and security checks for the scripts, the Python, and the
  workflows, and the tests on Linux and macOS. CodeQL, dependency review, and OpenSSF
  Scorecard run alongside.
- Git hooks refuse a commit on `main`, your own settings files, secrets, private names, and
  images nobody has looked at. Turn them on with `git config core.hooksPath .githooks`.
- Tests check that nothing in the repository describes a real home network, that every link
  in the docs leads somewhere, and that no test reaches the network.
- Renovate keeps the pinned versions current.
- `./ok3d check` says whether this machine is ready and the settings are valid. `./ok3d apply`
  makes the data root's folders, ok3d's own certificate authority, and the k3d cluster, then
  deploys two Helm releases: `ok3d-platform` (cert-manager) and `ok3d` (the namespaces and the
  web pages' certificate). `./ok3d delete` deletes the cluster and keeps the data root, so
  `./ok3d apply` brings it back.
- Settings live in `settings.yaml`, started from `settings.example.yaml`. A schema refuses
  values that can't work, with the reason, before anything changes. Devices and secrets have
  examples too (`devices.example.yaml`, `.env.example`), for the releases that use them.
- The certificate authority can only vouch for names under your ok3d domain, so trusting it
  on a device can't let it impersonate any other site.
- Every ok3d namespace refuses pods that run as root, keep capabilities, or can escalate
  their privileges (Kubernetes' restricted Pod Security Standard).
- `docs/architecture.md` shows how ok3d's pieces fit and how you set it up, in two diagrams
  with light and dark versions. Diagrams start as Mermaid files in `docs/diagrams/`;
  `scripts/diagrams.sh` renders them to PNG with a pinned mermaid-cli, and a test fails when
  an image no longer matches its source.
- `tests/vm/cloud-init.yaml` makes the test VM: a generic Ubuntu server with ok3d's
  prerequisites.
- `SECURITY.md`, `CONTRIBUTING.md`, and templates for pull requests and issues.

## 0.2.0 (2026-10-27)

The old stack's last version, before the rebuild replaces it. A review found that it
collected metrics but couldn't tell anyone about a problem: alerts went nowhere, the UniFi
alert rules used metrics that don't exist, the probes weren't scraped, and syslog never
arrived. [PLAN.md](PLAN.md) lists every finding.
