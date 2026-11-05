# Changelog

## 0.5.3 (unreleased)

## 0.5.2 (2026-11-05)

### Upgrading

- From 0.5.1, press **Look for a new release** on the Dashboard's Home, then **Upgrade now**
  ([docs/upgrading.md](docs/upgrading.md#from-the-dashboard-from-051)), or run
  `./ok3d upgrade v0.5.2` on the server. From 0.5.0 or 0.4, run the installer again, which
  moves straight to 0.5.2. Then check your settings, delete the cluster, and back up the data
  root as [docs/upgrading.md](docs/upgrading.md#from-050-or-04) shows, and finish with
  **Check** and **Apply** on the Dashboard.
- Check now refuses a `devices.yaml` with two devices of the same name, a `behind` that names
  itself or no device in the file, or one device with the same metrics port twice, instead of
  making objects that clash. The upgrade runs Check first, so with any of those it stops and
  moves back to 0.5.1, saying which device: fix it in `devices.yaml` (on the Dashboard's
  Devices page, or on the server), then upgrade again.

### Changes

- Apply's question no longer says an upgrade restarts the gateway when it doesn't. Check
  counted any change to a running part as a restart, even the chart's version label, which
  every release changes and which restarts nothing. It now counts a restart only when the
  part's pod template or replica count (or, for Prometheus and Alertmanager, their spec)
  changes. So the upgrade from 0.5.0 to 0.5.1 never restarted the gateway, though 0.5.1's
  notes said it did.
- The Maintenance page no longer says "No maintenance windows" before ok3d has read them from
  Alertmanager, after a fresh install, say. It says it hasn't read them yet, with **Read them
  now**. And when lines in the helper's note can't be read (a damaged file, say), it says how
  many, instead of saying there are none.
- A critical alert without a device (one of Kubernetes' own, say) no longer holds back every
  warning without one, UniFi's among them. Holding back warnings now needs both alerts to
  name the same device.
- HostRaidDegraded now fires for an array that's missing a disk, the usual state after a
  failure. It used to wait for a disk marked failed, which mdadm often takes out first.
- DeviceFlapping's text counts what it measures: "changed between up and down 14 times", not
  "went up and down 14 times" for seven drops. An expired device certificate says it has run
  out, instead of "runs out in -3d".
- The Devices dashboard's ping panel shows each ping's round trip, as it says, instead of the
  whole probe (with the name lookup), and its count of firing alerts leaves out
  InfoInhibitor.
- Check warns when `unifi.url` is `http://`, since the UniFi API key then crosses your
  network unencrypted.
- The certificate and 404 answers from the gateway carry the same security headers as every
  page.
- The docs no longer say `behind` turns a failed switch into one alert: that comes in 0.7.
  Until then it's carried on the device's alerts. `protected` is marked as coming in 0.9.
- Running the installer again no longer moves a checkout that has `./ok3d upgrade` (0.5.1
  and newer) to a newer release, since that skipped the release's signature check and the
  cluster's remake. It says to run `./ok3d upgrade` instead. Run again on the same release,
  it installs that release again, as before.
- `./ok3d install` can no longer be made to write the Dashboard's new certificate and key into
  another folder: a link in `dashboard/tls/` (which the Dashboard's container can write) to a
  folder is now replaced, not followed.
- Keeping the certificate authority now needs its domain to match exactly. Changing the
  domain to a shorter one it contains (noc.example from noc.example.org, say) used to keep an
  authority that can't vouch for the new names.
- Check looks for Python 3.12 or newer, and `./ok3d install` refuses unless the system's own
  `/usr/bin/python3`, which the helper runs, is 3.12 or newer. ok3d also refuses a checkout,
  settings, or devices path with a space or `*`, `?`, or `[` in it, which broke Check and
  Apply.
- When openssl can't make the certificate authority, Apply says why. A missing or unsafe `.env`
  is said once among Check's problems, not as every secret being empty, Check says when `.env`
  is a folder, and a `.env` that's a link is judged by the file it leads to. A value in `.env`
  loses its quotes only when they match. Install says when Docker isn't running.
- When an upgrade's install fails and installing the old release again fails too, the
  upgrade says so, instead of saying everything is back.
- Apply turns off again when `settings.yaml` or `devices.yaml` changes on the server after
  a Check, so the changes Home lists under Apply come from the files that Check read. A save
  from the Dashboard no longer overwrites a change made on the server while the save was
  being checked.
- After the Dashboard couldn't write a request for the helper, it no longer says the helper
  is busy for the next 10 minutes. And the helper now answers a request that hits an error
  it didn't expect, instead of leaving it marked running, which kept every button busy until
  the helper restarted.
- What's next says Grafana's password is your `OK3D_ADMIN_PASSWORD` when you've set one in
  `.env`, instead of pointing to a file ok3d doesn't make then.
- Opened at an address other than the one the installer printed (the server's IP address,
  say), the Dashboard still refuses its forms, sign-in included, but now names the address
  where they work.
- The helper's last answer says what it did in words ("Saving settings.yaml finished..."),
  not with ids like `save-settings`. A `settings.yaml` the Dashboard can't show (a link, or
  over 64 KB) is no longer reported as missing.
- Maintenance: a window for more than 50 devices is refused with a message that says so. A
  window that hasn't started has **Cancel** instead of **End now**, and the page's inputs
  look like the rest of the Dashboard's. `./ok3d maintenance` no longer ends in a Python
  error on a silence of an unexpected shape (odd matchers, or a time with no zone or out of
  range) or a damaged line in the helper's note.
- The Basic NOC card no longer says it watches your internet link: that comes in 0.7.
- The simulated network's devices answer a POST whose length is negative or not a number
  with an error, where one used to stop the handler or wait for the client to hang up, and
  drop a client that goes quiet for 10 seconds.
- The UniFi dashboards: every panel says what it shows when you hover over its title. The
  clock panel, which needed a plugin ok3d's Grafana doesn't have, is gone, and the pie charts
  use Grafana's own pie chart settings. The site latency gauge's colors match its units, and
  the speed test ping reads in milliseconds. The links lead to ok3d's UniFi docs and
  unpoller's site, the 30-second smoothing (which drew nothing) is gone, and the upstream
  author's notes are rewritten for ok3d.
- The docs, from the review: the README's commands clone the latest release instead of `main`,
  and name Helm 3.13. The steps for upgrading from 0.5.0 or 0.4 now check your settings, delete
  the cluster, and back up the data root before Apply. `SECURITY.md` says which protections
  hold now and which come later, and that the ping checks need no extra capability. Smaller
  fixes in the architecture, demo, certificate, AI install, alerts, and runbook pages, both
  under-the-hood pages (running the Dashboard from the checkout now works as written), the bug
  report form, and the setup diagram. The Settings page's screenshot, which no page showed, is
  no longer taken.
- When a path can't go in the helper's service file, `./ok3d install` now names the helper's
  Python too.
- Prometheus's and Alertmanager's pages are quicker: the gateway checked the admin login's
  hash at bcrypt cost 12 on every request, about 400 ms each time, for every request a page
  makes. It's cost 5 now, a few milliseconds. ok3d's own admin password is 18 random bytes,
  far too many to guess at any speed. The gateway's limit lets 100 requests through at once
  (it was 20), so a page load isn't refused. The limit never applied to wrong passwords, so
  Check now warns when an `OK3D_ADMIN_PASSWORD` of yours in `.env` is shorter than 20
  characters, and docs/certificate.md says how to change it, Grafana's copy included.
- Check refuses a `.env` that others can read even with every part switched off. It used to
  say Ready, and Apply then stopped partway.
- The dead man's switch hears from ok3d every minute, as the docs say. It was every 2
  minutes, since Alertmanager skipped every other repeat.
- Check warns below 4 GiB of free memory, not 7: ok3d 0.5 uses about 2 GiB. The README and
  the AI install's steps say the same, and the first Apply is said to take about 25 minutes,
  as it did on the test VM.
- For contributors: an emptied or unreadable private-names list now stops a commit instead of
  turning the check off, the privacy test shows as skipped without a list, an exact copy of
  git's scissors line typed into a message hides nothing, and the tests can no longer act on
  this repository when the pre-push hook runs them. Dashboard and helper tests that could
  pass or fail by luck no longer can, and a new one checks that whatever a finished `./ok3d`
  left running is stopped.

### Known issues

Both were in 0.5.1 too. The fixes are planned for 0.5.3.

- A maintenance window added or changed in the 15 minutes before an upgrade can be lost:
  Alertmanager saves its silences every 15 minutes, and the upgrade deletes the cluster without
  letting it save first. Add the window after the upgrade, or wait 15 minutes after adding it.
- If the server restarts while an upgrade is making the cluster again, **Apply** on the
  Dashboard fails with "another operation (install/upgrade/rollback) is in progress". Follow
  [docs/upgrading.md](docs/upgrading.md#if-an-upgrade-stops-partway) for a restart, which
  deletes the cluster first, or run `./ok3d delete --yes`, then `./ok3d apply`, on the server.

## 0.5.1 (2026-10-30)

### Upgrading

- From 0.5.0 or 0.4, run the installer again, as for 0.5.0
  ([docs/upgrading.md](docs/upgrading.md#from-050-or-04)). If ok3d isn't in `~/ok3d`,
  put `OK3D_DIR=/path/to/ok3d` before `sh`. Then **Check** and **Apply** on the Dashboard.
  Apply now asks first: from 0.5.0 it restarts the gateway, so ok3d's pages are unavailable
  for a moment, and the rest changes without stopping anything.
- From 0.5.1 on, the Dashboard upgrades ok3d itself: **Look for a new release** on Home.
- Apply's question needs Helm 3.13 or newer to know what would change; with an older Helm,
  Check warns, and Apply always asks.

### Changes

- Upgrades from the Dashboard: **Look for a new release** on Home asks GitHub for ok3d's
  releases (ok3d never does on its own), and offers a newer one with a link to its notes and
  its command. **Upgrade now** backs up your settings, moves ok3d to the release, checks and
  installs it, then deletes the cluster, backs up the certificate authority, Grafana, and
  Alertmanager, and makes the cluster again. If the new release's check or install fails, it
  moves back and the cluster isn't touched. Home shows each step as it happens.
- `./ok3d upgrade` does the same on the server: with nothing after it, it says whether a newer
  release is out; `./ok3d upgrade vX.Y.Z` moves to it.
- An upgrade takes only a release whose tag is signed with ok3d's release key, checked against
  `deploy/release-signers` as your copy has it. Releases are signed from 0.5.0.
- While an upgrade runs, the helper refuses everything else, and the Dashboard's Check,
  Apply, and saves are off.
- Apply asks first when it would restart or stop part of the running cluster. With a
  cluster running, Check now lists what Apply would restart, stop, or start, from a
  server-side dry run compared with what's deployed, and Home shows it under Apply. If
  anything would restart or stop, Apply opens a page naming those parts, with **Apply
  anyway**. `./ok3d apply` asks the same on a terminal; `--yes` skips the question.
- Maintenance windows: times when alerts don't notify you, for all of ok3d or the devices you
  choose, from now for a length or between two times. Alerts still fire and show in Grafana,
  and the dead man's switch is never silenced. On the Dashboard's new Maintenance page, and
  with `./ok3d maintenance` on the server. Home says while one is on.
- Each Dashboard page shows what its buttons do on the server: `./ok3d check` and `./ok3d
  apply` on Home, the file to edit on Settings and Devices, the `settings.yaml` lines each
  ready-made setup writes on Setup, and the `.env` line each key goes into on Keys.

## 0.5.0 (2026-10-29)

### Upgrading

- From 0.4: if you cloned ok3d somewhere other than `~/ok3d`, note where. Then run the
  installer, which brings that copy to 0.5.0, keeps your settings and certificate authority,
  and starts the Dashboard (`OK3D_DIR` says where your copy is; leave it out for `~/ok3d`):
  `curl -fsSL https://raw.githubusercontent.com/southsidedean/observability-k3d/main/install.sh | OK3D_DIR=/path/to/ok3d sh`.
  Then Check and Apply on the Dashboard. The installer stops if you changed ok3d's own files
  (your settings are safe: they're not ok3d's). [docs/upgrading.md](docs/upgrading.md) has
  the steps.
- If you run the simulated network, run `./ok3d demo down` and `./ok3d demo up` once after
  upgrading: its devices from 0.4 don't come back after a restart, and new ones do.
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
  exactly one of those two. [docs/helper-under-the-hood.md](docs/helper-under-the-hood.md) says how it works.
- The Dashboard's first part: its image, `ghcr.io/southsidedean/ok3d-dashboard`, for amd64 and
  arm64, behind a sign-in of its own, over HTTPS only.
  [docs/dashboard-under-the-hood.md](docs/dashboard-under-the-hood.md) says how
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
- [docs/dashboard.md](docs/dashboard.md) walks through installing and each of the
  Dashboard's pages, with screenshots in light and dark. `scripts/screenshots.sh` takes them
  all on the simulated network, so they can be refreshed in one run.
- Installing with an AI assistant: the README has a prompt to paste into one that can run
  commands on your server, such as Claude Code. It installs what's missing (you run each
  `sudo` command yourself), runs the installer, and stops once the Dashboard is running.
  [docs/install-with-ai.md](docs/install-with-ai.md) has the rules and steps it follows.
- `./ok3d install` prints the Dashboard's password only when its output is a terminal.
  Otherwise, as when an AI assistant or a log reads it, it says which file holds it.

### Fixes

- The Dashboard's forms work in a browser. It sent `Referrer-Policy: no-referrer`, which makes
  browsers send `Origin: null` on a form, and its own Origin check then refused them all,
  sign-in included. It now sends `same-origin`. (No release had the Dashboard yet.)
- Grafana's panels load in a browser. The gateway sent `Referrer-Policy: no-referrer`, which
  makes browsers send `Origin: null` on Grafana's own requests, and Grafana refused every
  one ("origin not allowed"), so each panel showed an error. It now sends `same-origin`,
  which still keeps your pages' addresses from other sites. Grafana also trusts its own
  name (`grafana.<domain>`) as an origin: the gateway passes Grafana its
  in-cluster name, so Grafana took the browser's real Origin for another site's and refused
  its queries too. In 0.4.0, Grafana's dashboards show no data in a browser until you
  upgrade.
- The simulated network's devices come back after the server restarts, instead of all
  showing as down. One you failed with `./ok3d demo fail` stays failed.
- Grafana's Devices dashboard no longer shows a `namespace` column in its table of checks.
- Grafana can have 1 GiB of memory, up from 512 MiB. It uses about 400 MiB once started,
  and opening a dashboard took it over 512 MiB, so it was killed and restarted.
- A client that sends its request to the Dashboard a byte at a time can't keep a connection:
  each one has 60 seconds in all.
- When the Dashboard refuses a form, such as a file that's too big or a save after your
  session ran out, the browser shows the refusal or the sign-in page, not a reset connection.
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
