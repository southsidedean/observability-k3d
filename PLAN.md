# Plan: ok3d, a home network operations center on k3d, with AI agents

Status: planning (2026-10-27). Nothing below is built yet. `v0.2.0` is the old stack's last
version (the `scripts/cluster-setup-k3d-observability-everything.sh` stack). It keeps
working until 0.4.0 replaces it. The roadmap ends in 1.x.

## Goal

NOC-level monitoring and alerting for a home network that anyone can build from the docs.
You know when something on your network breaks, before anyone in the house tells you.
Alerts reach your phone. Every device, link, and service shows on one board, with the logs
and traces behind it. You get one sign-in for every page, and agents that can read all of it,
explain what went wrong, and, with your approval, fix the simple things.

You set it up on a web page: install the Dashboard, choose what you want, check it, and
apply. The Dashboard creates the cluster and everything in it.

The repository holds no one's own setup. Your settings, devices, and secrets live in files
that are never committed, and the repository carries a commented example of each.

## What went wrong last time

A review on 2026-10-27 found that the old stack collected metrics but couldn't tell anyone
about a problem. Each of these is fixed in the roadmap below:

- Alerts went nowhere: Alertmanager had no receivers, and Grafana's contact points were off.
- The UniFi alert rules queried metric names unpoller doesn't export (`unifi_device_*`
  instead of `unpoller_device_*`, and percentages instead of 0 to 1 ratios), so they could
  never fire.
- The ping and website probes were never scraped (missing the chart's `release` label), and
  the blackbox exporter had no `icmp` module and no permission to ping.
- Syslog never arrived. The Promtail in loki-stack only reads RFC5424, rsyslog sends
  RFC3164 by default, and UniFi sends syslog only over UDP while the stack listened only on
  TCP.
- k3s doesn't expose the scheduler, controller-manager, etcd, or kube-proxy metrics, so the
  chart's alerts for them would have fired forever.
- Prometheus's host-folder volume was removed (commit `2e1b018`), so a redeploy would lose
  its history.
- Grafana and the Kubernetes API were open to the whole network, Grafana with a well-known
  default password, and the kagent UI had no login at all, with an OpenAI key behind it.

## Decisions

| Question | Decision |
|---|---|
| Name and logo (decided 2026-10-27) | **ok3d**, short for observability-k3d, the way kia is short for kodi-iptv-assistant: the name in the docs, on the pages, and on commands (`ok3d doctor`). It's also the cluster's default name. Its mark is kia's screen and stand with an amber pulse line over a row of device tiles, in kia's colors and on kia's grid (`images/ok3d-logo.svg`, and `ok3d-logo-dark.svg` for dark mode). The repository keeps its name. |
| Where it runs | One k3d cluster of its own on one Linux server, separate from anything else running there. The cluster's name, ports, and Docker network come from settings, so it can sit next to other k3d clusters. |
| Standalone | Nothing here depends on another project. Other stacks' exporters (node-exporter, GPU, Plex, SMART) can be listed as scrape targets like any device, and other projects' MCP servers can be added as remote tools, but ok3d never reads another stack's Prometheus and never shares config, code, or services with it. |
| The cluster is disposable, the data isn't | Upgrading means deleting the cluster and creating it again with newer versions. Everything stateful lives in host folders under one data root, so a new cluster picks up where the old one left off. This worked well with the old stack and stays the core rule. |
| Dashboard first (decided 2026-10-27) | The Dashboard runs **outside the cluster**, as one locked-down container on the host, because it's what creates the cluster and later recreates it to upgrade. You install it first, configure the deployment on it, and apply; it then creates the k3d cluster and deploys everything. Later it changes settings, adds devices, and runs upgrades. It keeps working when the cluster is down, which is when you need it most. |
| The helper | The Dashboard can't run anything itself. A small helper on the host (`ok3d-helper`, a systemd user service running as you) does that for it, the way kia's Stack page works with the kia-stack service. The page leaves a request file: check or apply, choices from fixed lists, a random id, less than 5 minutes old, at most 4 KB. The helper checks every value again and refuses anything else. It assumes the Dashboard's container may have been taken over: the most it will ever do is what you could do with the `ok3d` command yourself. |
| The `ok3d` command | Everything the Dashboard does, the terminal does too: `ok3d check`, `ok3d apply`, `ok3d upgrade`, `ok3d backup`, `ok3d doctor`. The Dashboard shows each choice as the command it equals. |
| Packaging | Helm, as two releases in order. **`ok3d-platform`**: the custom resource definitions (Gateway API, cert-manager, the Prometheus operator, kagent), cert-manager, and Istio's charts in the order Istio needs. **`ok3d`**: everything else, as one umbrella chart with pinned dependencies (`Chart.lock`). A values schema refuses typos. The Dashboard's Check is `helm template` plus the schema plus kubeconform, without touching the cluster; Apply is `helm upgrade --install`. Recreating the cluster to upgrade gives every upgrade fresh custom resource definitions, which Helm alone doesn't update. |
| Images and language (decided 2026-10-27) | Two images, on opposite sides of a trust boundary. **`ok3d-dashboard`** runs on the host and holds the Dashboard. **`ok3d`** runs in the cluster: one image with several entry points (the ok3d MCP tools, the UniFi MCP server, the action runner, the Approvals page, the layout builder, the digests), each run as its own pod with its own permissions. Taking over anything in the cluster must not lead into the Dashboard. Both are written in Python, like kia, and built on Chainguard's Wolfi base for amd64 and arm64. They run as non-root with a read-only filesystem. The helper is a host script, also in Python, because it parses requests it can't trust. |
| Your settings | `settings.yaml` for settings, `devices.yaml` for devices, `.env` for secrets, and `local/` for anything private of your own (below). All are gitignored, and each has a committed, commented example. The Dashboard writes them through the helper, and you can edit them by hand. `chart/values.yaml` holds the defaults; you never edit it. `vars.sh` is retired. |
| Secrets on the page | The Dashboard sets secrets in write-only fields. The helper writes them to `.env` (mode 600), and the page only ever shows whether each is set. No secret is ever sent back to a browser. |
| Switches | Every module (UniFi, Plex, SNMP, UPS, syslog, the mesh, agents, remote access) and every action is one switch in settings, shown as a toggle on the Dashboard. Each module is off until you turn it on, except the core: metrics, alerts, and the front door. |
| Setup cards | The Dashboard offers ready-made setups as cards (*Basic NOC*, *Network NOC*, *NOC with logs*, *NOC with agents*, *Everything*), each saying what it's for, what it needs (memory, a UniFi API key), and what it will ask of you. Or you choose the parts yourself. A card appears in the release its parts come in: 0.5 has Basic and Network (decided 2026-10-28). Each card's memory comes once it's measured on the test VM. The agents card needs `modules.agents`, which only the server may change today, so 0.9 decides how the Dashboard turns agents on. |
| Nodes | One k3s server and no agent nodes. That uses less memory, kagent's sandbox folder must be on the server anyway, and every host-folder volume lands on the one node. |
| Metrics | kube-prometheus-stack, pinned, with the k3s control-plane scrapes and rules turned off. |
| Logs | The `loki` chart in single-binary mode with retention on, and Grafana Alloy collecting pod logs and syslog. loki-stack and Promtail are retired (both deprecated). |
| Syslog | Alloy listens for both RFC3164 and RFC5424, over UDP and TCP, on a LoadBalancer Service published by k3d. It doesn't go through the gateway, which has no UDP listener. |
| Devices | `devices.yaml` lists every device: name, address, role, what it's connected through, which checks apply, and whether it's `protected` (no action may ever touch it). Probes, scrape targets, and the status board are generated from it. The Dashboard has a Devices page for it, and offers to add each new device that joins the network. |
| Alerts | Alertmanager sends to ntfy and email. Critical alerts repeat more often than warnings. Alertmanager's always-firing Watchdog alert pings an outside dead man's switch, such as healthchecks.io, so you hear about it when the NOC itself goes down. |
| Alerts that know the layout | UniFi reports which port each device connects through. ok3d builds the network's layout from that (and from `devices.yaml` for anything else) and holds back alerts for everything behind a failed device: a dead switch is one alert, not ten. When the internet link is down, the internet checks are held back too. No hand-written rules. |
| Alerts on targets | Services with a reliability target (the internet link, DNS, Wi-Fi, the NOC's own pages) alert on how fast they use up their error budget, rather than on single thresholds, so a short blip doesn't page you and a slow decline doesn't go unnoticed. |
| Maintenance windows | Set on the Dashboard ("UniFi firmware, Tuesday 23:00 to 00:00"): matching alerts are silenced for the window, the board shows it, and the agents know about it. |
| What changed | Every change ok3d can see is a marker on every graph: UniFi configuration changes and firmware updates, ok3d deploys and upgrades, new devices, and every action taken. Most outages follow a change. |
| North/south: agentgateway (decided 2026-10-27) | agentgateway, in standalone mode (its own config file, generated by the chart into a ConfigMap), is the gateway for everything coming into the cluster or leaving it: the only way into the web pages, the only route to the AI model, and the place MCP tools are served from. It starts the trace for each request. Something else is used only where agentgateway can't do the job: syslog over UDP has its own Service. kgateway is retired. |
| East/west: Istio ambient (decided 2026-10-27) | Open-source Istio in ambient mode is the data plane between workloads. ztunnel gives every pod in the mesh mutual TLS and a workload identity, and AuthorizationPolicies use that identity alongside the NetworkPolicies. Istio's waypoint proxies go only where layer-7 metrics or spans are wanted. No sidecars. |
| Traces | Tempo keeps the traces (7 days by default), with Alloy as the OpenTelemetry collector for agentgateway, the waypoints, and kagent. Grafana links traces, logs, and metrics to each other, and Tempo's service graph and request metrics go to Prometheus. |
| Certificates | Two paths, both through cert-manager, picked with `tls.mode`. **Self-issued is the default** (decided 2026-10-27): the installer makes one certificate authority in the data root. The Dashboard's certificate comes from it, and the cluster's cert-manager issues from it (one wildcard certificate for `*.<domain>`), so you trust one authority, once, and a new cluster keeps it. A page serves the authority's certificate for download, and the docs show how to trust it on each kind of device. **Public certificates from Let's Encrypt** come in 1.1. Changing paths changes only the issuer. |
| Names | Each page gets its own name under one domain (`grafana.<domain>`, `auth.<domain>`, `agents.<domain>`, ...). Subdomains avoid Grafana's sub-path problems. With self-issued certificates the default domain is `noc.home.arpa` (`home.arpa` is reserved for home networks), and the names come from a local DNS record on your router or local DNS server. Public certificates need a domain you own. |
| Sign-in | Until 0.8, each page has its own login behind the gateway's TLS. From 0.8: Authelia as the identity provider (users in a file to start, LLDAP later), and agentgateway as the OIDC client in front of every page in the cluster. The gateway passes the signed-in user on in trusted headers and strips the token. NetworkPolicies let only the gateway reach the apps. agentgateway's OIDC client can't trust a private certificate authority, so the gateway reaches Authelia inside the cluster over HTTP, with the forwarded headers set so Authelia computes a consistent https issuer, and checks tokens against a local copy of Authelia's keys (the offline setup kia's proof of concept used). With public certificates, the gateway can use OIDC discovery instead. |
| The Dashboard's sign-in | Its own password, printed once by the installer, always works, because the Dashboard has to work when the cluster (and Authelia with it) is down. From 0.8 it also signs in through Authelia, as its own OIDC client, for everyday use. |
| Grafana's sign-in | From 0.8, Grafana trusts the gateway's user header, and Authelia groups map to Grafana roles (admins are Admin, everyone else is Viewer). |
| Remote access | Optional: Tailscale, so the Dashboard and the approval page work from your phone away from home without opening a port. Off by default. |
| Agents | Until 0.9 chooses (see 0.9): kagent 1.0 (Agent Substrate), pinned; until GA, the newest 1.0 alpha. kagent's packaged agents are used only where they fit (observability, PromQL, and Kubernetes, limited to ok3d's namespaces and read-only), with their prompts as starting points for ok3d's own. kagent-tools never gets cluster-wide access. Agents hold no model key; the gateway adds it. The built-in bash and file tools are off unless an agent needs them. Prompt caching is on. |
| Model | Claude, through the gateway, with its own API key, in its own Anthropic Console workspace with a monthly spend limit, on top of the gateway's budget. Other providers can be configured through the gateway. |
| MCP tools | **Use** what exists: Grafana's MCP server with `--disable-write` and a Viewer service account (Prometheus, Loki, alerts, dashboards), and kagent-tools for Kubernetes, limited to ok3d's namespaces. **Build** an ok3d tools server first: what's down, a device's status, what changed in the last hour, an alert's history, the internet link's health, built around `devices.yaml` and ok3d's rules, so agents get reliable answers instead of writing queries. **Evaluate, then probably build** a UniFi server on Ubiquiti's official Network Integration API, starting from a view-only admin's key. **Plex** read tools come with the Plex module. All of them are served through the gateway. The ok3d tools server also offers starter prompts, as kia's MCP server does: *network checkup*, *explain this alert*, and *what changed today*. |
| Remote MCP servers | `settings.yaml` can list other MCP servers, such as kia's. The gateway holds each one's key in `.env` and checks its certificate (including a self-issued one, which kagent itself can't), and the agents never see the key. The docs use kia as the example. |
| Private additions | `local/` (gitignored) holds extra values files and agent definitions that `ok3d apply` loads after everything else: your own MCP servers and agents for things that aren't public, without a fork. |
| What agents may do (decided 2026-10-27) | Four tiers. **1. Read**: everything above; ships first. **2. Approved actions**: a short list of safe, undoable actions (below), each its own narrow tool and its own switch; the agent asks, a signed-in admin approves, it runs, and the gateway logs it. **3. Plans**: bigger changes are written as a plan file you review and apply with a script that has no AI in it. **4. Never**: firewall, VLAN, routing, DNS, Wi-Fi security, credentials, and firmware. No tool exists for them, so no planted instruction can reach them. |
| Approvals (decided 2026-10-27) | On both the page and your phone. The Approvals page lives in the cluster behind sign-in, for the admins group only, and Authelia asks for a second factor there. ntfy notifications carry a **view** action that opens the page; they never approve anything in one tap, since anyone who knows an ntfy topic can read it. A request expires after 15 minutes. An agent can't approve its own request. |
| Plex (decided 2026-10-27) | An optional module that watches Plex as a service on the network: whether it answers, remote access, streams and transcodes, the load they put on the server, and how much of your upload remote streams use. It scrapes a Plex exporter you already run, or runs its own, pinned. This doesn't duplicate kia's Plex dashboards, which watch Live TV and players. |
| Your internet link | A record of every outage with its length, latency, packet loss, DNS time, and a speed test at a set interval (with a cap), with a monthly report. Useful when talking to your ISP. |
| Digests | A daily or weekly summary by ntfy or email: uptime, incidents, new devices, the biggest users of the internet link. With agents on, a morning briefing from an agent, started by a Kubernetes CronJob (kagent has no scheduler). |
| The NOC watches itself | Failed scrapes, logs Loki couldn't take, syslog messages dropped, a full data root, and an ok3d backup that's too old all alert. So does a UniFi controller whose own backups have stopped. |
| The simulated network (decided 2026-10-27) | A small fake network for tests, screenshots, and trying ok3d without UniFi gear: recorded `/metrics` output from unpoller and the other exporters, served as if live, and a few small containers that answer ping and HTTP, one of which can fail on cue. CI's smoke test, every screenshot in the docs, and the docs' examples use it, so none of them show a real network. `ok3d demo` starts it. |
| Your data stays home | ok3d sends nothing anywhere except what you configure: alerts to ntfy and email, the dead man's switch, model calls, and backups. There's no telemetry. The README and `SECURITY.md` say so. |
| ok3d's own metrics | The Dashboard, the helper, and every ok3d component in the cluster expose `/metrics`, so the NOC watches its own parts. `docs/metrics.md` lists every metric, as kia's does. |
| Backups | `ok3d backup` copies the data root's small, precious parts (Grafana, Authelia, the certificate authority, the settings) to another host or a NAS, on a schedule. Prometheus, Loki, and Tempo are optional, since they're large. Each backup is encrypted with age to a public key, so the schedule needs no secret on disk; only a restore needs the private key, which the user keeps somewhere else. |
| Releases | Development and testing happen on a test VM. `main` is tested there, and production runs the latest release, tagged with a CHANGELOG entry. Deploying a release means upgrading from the Dashboard, which recreates the cluster from that release. |
| Not now: Argo CD | GitOps wants your settings in a git repository, and ok3d deliberately keeps them out of one and on the Dashboard. Argo CD would also have to be bootstrapped into each new cluster, and costs about 0.5 to 1 GiB, mostly to fix drift that a cluster nobody edits by hand doesn't have. Revisit in 1.x as an optional GitOps mode for people who keep their settings in a private repository (Flux is lighter for that). |

## Pieces

| Piece | Where | Job |
|---|---|---|
| **The Dashboard** | a container on the host | Setup, settings, devices, secrets, maintenance windows, upgrades, and backups. Works when the cluster doesn't. |
| **ok3d-helper** | a systemd user service on the host | Runs the `ok3d` command for the Dashboard, and nothing else. |
| **Prometheus** | `monitoring` | Collects and keeps the numbers (30 days by default). |
| **Alertmanager** | `monitoring` | Sends alerts: grouping, repeating, holding back alerts behind a failed device, maintenance windows, and the dead man's switch. |
| **Grafana** | `monitoring` | Dashboards, including the NOC board. |
| **Loki** | `monitoring` | Keeps the logs (30 days by default). |
| **Tempo** | `monitoring` | Keeps the traces. |
| **Alloy** | `monitoring` | Pod logs, the syslog listener, and the OpenTelemetry collector. |
| **blackbox exporter** | `monitoring` | Ping, DNS, HTTP, TCP, and certificate-expiry checks for everything in `devices.yaml`. |
| **unpoller** | `monitoring` | UniFi controller metrics. Optional. |
| **SNMP, NUT, and Plex exporters** | `monitoring` | Switches, NAS, and UPS that aren't UniFi, and Plex. Optional. |
| **agentgateway** | `gateway` | North/south: TLS, sign-in, security headers, the model route, and MCP. |
| **Istio ambient** | `istio-system` | East/west: istiod, istio-cni, ztunnel, and waypoints where needed. |
| **cert-manager** | `cert-manager` | Issues and renews the certificates. |
| **Authelia** | `auth` | Accounts, groups, second factors, and OIDC. |
| **The Approvals page** | `auth` | Approve or turn down what an agent asks to do. |
| **kagent** | `agents` | Agents and their chat page. |
| **MCP servers** | `agents` | Grafana's, ok3d's own tools, UniFi, and Plex. |
| **Action runner** | `agents` | Carries out approved actions, one narrow tool each, and checks the result. The only piece with write access to anything, and only to what the switched-on actions need. |

On the hosts you monitor, not in the cluster:

| Piece | Job |
|---|---|
| **Alloy** (Linux) or **node_exporter** (macOS) | Each computer's own numbers and, with Alloy, its system log. The docs give a ready config. |
| **Syslog** | Routers, switches, access points, and anything else that can only send syslog. |

## Actions

The first list (decided 2026-10-27). Each is off until switched on, works only through
approval unless marked otherwise, and never touches a device marked `protected`.

| Action | Through | Guardrails |
|---|---|---|
| Blink a device's locate light | UniFi | No approval needed: it can't harm anything, and helps you find the device. |
| Restart an access point or switch | UniFi | Never the gateway (it would take the network and the NOC down). At most once per device every 30 minutes. Checks the device came back. |
| Power-cycle a PoE port | UniFi | Never a protected port. Checks the device on the port came back. |
| Make a Wi-Fi client reconnect | UniFi | For a client stuck on a bad access point. |
| Silence an alert | Alertmanager | 24 hours at most, with a reason, shown on the board. |
| Restart an ok3d component | Kubernetes | Only ok3d's own Deployments, such as a stuck exporter. |
| Refresh a Plex library | Plex | Only with the Plex module on. |

The second list, in 1.x: block or unblock a client, and run a speed test now. Every action is
written to Loki, marked on the graphs, and its result goes back to the agent and to you.

## The data root

One folder on the server, set by `host.dataRoot`. A dedicated filesystem is best. The
install doc shows how to make one with LVM, and how to grow it later.

```text
<host.dataRoot>/
├── dashboard/       the Dashboard's state, and outbox/, where it leaves requests for the helper
├── helper/         the helper's own folder: its answers, which the Dashboard can only read
├── prometheus/      the time series database
├── alertmanager/    silences and what was already sent, so a new cluster doesn't repeat alerts
├── loki/            logs
├── tempo/           traces
├── grafana/         Grafana's database: users' stars, edited dashboards, preferences
├── authelia/        its database (sessions, second factors); users.yml stays in your settings
├── certs/           the certificate authority (self-issued), or the ACME account key and the
│                    certificate (public), restored into each new cluster
├── gateway/         agentgateway's budget database, when agents are on (0.9)
├── kagent/          kagent's database
└── kagent-ate/      kagent's sandbox state, mounted at /var/lib/ate on the server node
```

The host check creates any missing folder with the owner and mode its app runs as. No folder
is world-writable. Before an upgrade, `ok3d backup` copies `grafana/`, `authelia/`, and
`certs/`, which migrate forward only or can't be made again.

## The host

What the server needs, and what the host check checks before anything is created:

- Linux with Docker, k3d 5.9 or newer, Helm, and kubectl. kagent 1.0 needs Kubernetes 1.37
  (pod certificates), and k3d 5.9 can run `rancher/k3s:v1.37.x`. The installer says which
  are missing and how to get them.
- About 11 GiB of free memory for everything (kagent's node alone measured 1.7 GiB at rest;
  the mesh and Tempo add about 1 GiB), and about 7 GiB with agents off.
- An x86-64-v2 processor or newer. Some images need more, and the check names any that won't
  run on this processor.
- inotify limits of at least 1024 instances and 1M watches (two k3d clusters on one host
  exhaust the defaults). The check prints the `sysctl` lines to add.
- The data root, on a filesystem that isn't overlay.
- Local DNS you can add records to (most routers can), for the stack's names.

## GitHub, tests, and releases

Set up the way kia's repository is (decided 2026-10-27; the settings and rulesets were
applied that day).

**The repository's settings**

- Squash merges only, with the pull request's title as the commit's title, and branches
  deleted after merging.
- A ruleset for `main`: changes only through a pull request, no force-pushes, no deletion,
  and the checks below required (added to the ruleset with the workflows in 0.3.0).
- A ruleset for release tags (`v*`): no deletion, no moving, no rewriting.
- Dependabot security alerts and updates, private vulnerability reporting, and secret
  scanning with push protection on. The wiki off; the docs live in the repository.
- Release tags are signed.

**Workflows.** Every action is pinned to an exact commit, and every workflow runs with the
least permissions it needs. Each job in `tests` is a required check on `main`. All of it
also runs locally with `scripts/check.sh`, which skips a tool you don't have installed (CI
installs all of them, so nothing is skipped there).

`tests` runs on every push and pull request, and weekly. Its jobs:

| Job | What it checks |
|---|---|
| **lint and security checks** | shellcheck on the scripts and hooks (POSIX `sh`), ruff and bandit on the Python (kia's rule set), mypy in strict mode, zizmor and actionlint on the workflows, hadolint on the Dockerfiles, Renovate's config validator, that every JSON file parses, the privacy check, that the Dashboard's colors stay readable in light and dark, and axe's accessibility checks on every Dashboard page (keyboard use, labels, focus). |
| **pytest** | On the oldest supported Python, the newest, and macOS, with a one-minute limit per test. The helper refuses every bad request, and Hypothesis fuzzes it with malformed, oversized, stale, and replayed requests, path tricks, and unknown choices. The MCP tools mark text from devices, logs, and Wi-Fi network names as untrusted, and never let an address or a key into an answer. Planted instructions are kept as test fixtures. The action runner never touches a protected device, never runs without approval, keeps its rate limits, and refuses an expired approval. The Dashboard keeps secrets write-only, won't Apply before Check, and every setup card makes valid settings. Tests for real-world failure, as kia has: settings files that are hand-edited, cut short by a full disk, or the wrong shape; one broken exporter or device not stopping the rest; the Dashboard saving while an Apply runs. An offline fence makes sure no test reaches the internet. |
| **charts** | `helm lint` and a full render with the example settings and every combination of setup card and module. The schema refuses what it should: an image tagged `latest`, a misspelled setting, an action whose module is off, an unknown device role. helm-unittest keeps the rules the rendered charts must hold. Every pod is hardened (non-root, read-only root filesystem, no privilege escalation, capabilities dropped). The NetworkPolicies and AuthorizationPolicies are in place. Agents have read-only RBAC and no Secrets. Write access is given only to the actions that are switched on. Every image is pinned. kubeconform checks every object in strict mode against the cluster's Kubernetes version, with schemas for the Prometheus, Istio, cert-manager, and Gateway API kinds. A memory budget: the memory requests in each setup card's render must fit what the docs say that card needs. |
| **alerts** | `promtool check rules`, and a `promtool test rules` unit test for every rule. Every metric a rule or a dashboard uses must appear in the recorded `/metrics` of the exporter it comes from, so a renamed metric fails here instead of silently never firing. `amtool check-config`, and tests of the routing: critical alerts reach you, the Watchdog reaches the dead man's switch, and maintenance windows and the network's layout hold back what they should. Loki's rules go through Loki's own checker. |
| **dashboards** | Grafana's dashboard-linter. Every panel uses a datasource that exists, with no `${DS_*}` left behind. The vendored dashboards' local patches still apply. |
| **images** | Both images built for amd64 and arm64 and started once (`--version`). Trivy fails on any fixable high or critical CVE (exceptions in `.trivyignore`, each with its reason). Grype gives a second opinion, as a report only. |
| **docs** | Every link leads somewhere, the house style holds, `docs/settings.md` matches what the schema generates, every alert has a runbook, every `.env` key is in `.env.example` and the docs, and every setup card is documented. The install doc's commands are pulled out and run by the smoke test, so the doc can't drift from what works. |
| **end-to-end smoke test** | A k3d cluster on the runner, with agents off to fit the runner's memory. The installer runs in CI mode, then Check and Apply go through the Dashboard's own API, the way a browser would. Then `ok3d test`: the targets are up, a test rule fires and reaches a test receiver, syslog arrives in both formats over UDP and TCP, the gateway serves TLS and redirects to sign-in, a NetworkPolicy blocks what it should, and the data survives the cluster being recreated. Secrets used in the test are canaries, and the run fails if any of them shows up in a log, a trace, a page, or an alert. From 0.5, an upgrade test: install the previous release, then upgrade to the pull request's code. |
| **mesh** | The smoke test with Istio ambient on, as its own job to keep run times down (from 0.8). |

The other workflows:

| Workflow | When | What |
|---|---|---|
| `codeql` | every push and pull request, and weekly | GitHub's CodeQL for the Python, in the Security tab. |
| `dependency review` | every pull request | Blocks a pull request that adds a dependency with a known vulnerability or an incompatible license. |
| `scorecard` | weekly | OpenSSF Scorecard: how well the repository itself is protected (pinned actions, branch protection, token permissions, signed releases), in the Security tab. |
| `mutation` | weekly | Mutation testing (mutmut) on the code that guards something: the helper, the action runner's guardrails, and the MCP tools' handling of untrusted text. If a change to that code gets past every test, a test is missing. |
| `upstream` | weekly | Whether the vendored dashboards have newer revisions. Opens an issue, never a change. |
| `images` and `image scan` | from 0.5.0 | Build the Dashboard's image (and the in-cluster one, once the first tool that runs in the cluster arrives), scan with Trivy before pushing, push, attach an SBOM and a provenance attestation, and scan the published images weekly. |
| `release` | a merge to `main` that changes the version | Tags the release and publishes its notes from `CHANGELOG.md`. Not built yet: releases are made by hand (CONTRIBUTING.md). A workflow can't sign the tag without a signing key in CI, which would be a decision of its own. |

**Updates:** Renovate keeps the pinned versions current: the actions, the Helm chart
dependencies in `Chart.yaml`, the image tags and base images (by digest), and the Python
dependencies. Dependabot handles Helm dependencies and image tags in values poorly. Renovate
opens one grouped pull request a month, for releases at least a week old, and security fixes
right away. Dependabot stays on only for security alerts.

**Considered for later** (2026-10-29): a self-hosted runner on a test VM, so the real
cluster, agents included, runs on every pull request instead of by hand (never run anything
by hand on it, or its runs break); and on that runner, a weekly job outside pull requests
that deploys the newest kagent and agentgateway, to catch a break in either before Renovate
proposes it (kia runs a weekly check of its own fast-moving upstream). GitHub's runners can't:
the smoke test there runs with agents off to fit their memory.

**Left to the test VM**, because CI can't do them: kagent with a real model, a real UniFi
controller, an ntfy notification on a real phone, trusting the certificate authority in a
real browser, and Tailscale. They're on the release checklist.

**Files:** `LICENSE` (AGPL-3.0), `SECURITY.md` (how to report a problem privately, and how
the stack limits the damage), `CONTRIBUTING.md` (branches, hooks, checks, releases),
`CHANGELOG.md`, a pull request template with its checklist, and issue templates for bugs
and features, with links to troubleshooting and private security reports.

**Git hooks** (`git config core.hooksPath .githooks`): pre-commit refuses commits on `main`,
of anyone's own settings files, of secrets, and of private names or addresses outside the
examples, anywhere in what the commit would hold and in its files' names; commit-msg refuses
them in the message. Private names come from a list kept in `.git/hooks/private-names`, on
your own machine and never committed: your host names, domains, and addresses, each plain
name also matched in its other spellings. The same check (`scripts/private-names.sh`) runs on pull
request descriptions and release notes before they're posted. A commit that adds or
changes an image needs `IMAGES_CHECKED=1`, set only after every image was looked at and its
metadata stripped. Pre-push runs the quick checks.

**Committing:** files are staged by name, never with `git add -A`, so nothing untracked (a
screenshot dropped into `images/`, say) goes in by mistake. Examples use stand-ins: addresses
like `192.168.1.20`, `192.0.2.x`, and `fd00::5`, and names like `my-server.lan` and
`noc.home.arpa`.

**Releasing:** user-facing changes collect in `CHANGELOG.md` under the next version, marked
unreleased. A release pull request sets the version and the date. Then the signed tag,
`gh release create` with that version's changelog section as the notes, a check that the
images (the Dashboard's, and the in-cluster one once it exists) were published for both
architectures and scanned, and a "Start X.Y.Z.dev0" pull request for the next one.

**Testing before a release:** CI covers what a runner can. Each release is also installed on
a test VM from scratch through the Dashboard, with the certificate authority trusted in a
browser, and upgraded from the release before, before production moves to it.

**The test VM** (decided 2026-10-27) is a generic home server, the case most people have: a
Multipass VM with Ubuntu 24.04 LTS, 8 CPUs, 16 GiB of memory, Docker, k3d, Helm, kubectl, the
raised inotify limits, and an empty data root at `/srv/ok3d`. Its setup is a cloud-init file
in `tests/vm/`, so anyone can make the same VM. It keeps snapshots: `base` (the prerequisites
and nothing of ok3d), restored before every install test and every screenshot run so each
starts clean, and one per release once installed, for upgrade tests. The same VM is the
screenshot environment.

## Quality, security, and docs (decided 2026-10-27)

These hold for every pull request, from 0.3 on.

**Done means:**

- Tests come with the change. A bug fix starts with a test that fails without the fix.
- Code and configuration are well commented. Each file starts by saying what it's for, and
  comments say why something is done the way it is wherever that isn't obvious from the code.
  This holds for scripts, Python, chart templates, values files and the values schema (every
  setting has a description, which `docs/settings.md` is generated from), settings examples,
  alert rules (each with a summary, a description, and its runbook link), dashboards (each
  panel says what it shows), and workflows. A part that's hard to follow without its comments
  counts as a defect in review.
- The docs change in the same pull request as what they describe.
- Everything a person reads is reviewed with the humanizer skill before it's committed: the
  docs, the README, this plan, runbooks, the CHANGELOG, comments, commit messages, pull
  request descriptions, release notes, the Dashboard's text, and alert and notification text.
- `CHANGELOG.md` has a line under the next version if users will notice the change.
- Every pull request gets an independent review before merging, from a person or from Claude
  Code's `/code-review`, and its findings are fixed or answered.
- Screenshots and diagrams are looked at before they're committed (below).
- Names that CodeQL would read as secrets are avoided: it flags any function or variable
  named like `*password*` or `*secret*`, even a description of one, and then flags it reaching
  a log.

**Coverage:** reported for all the Python. Branch coverage must be complete for the code that
guards something: the helper, the action runner's guardrails, and the MCP tools' handling of
untrusted text. Mutation testing checks those same tests weekly.

**Security** is built in from 0.3, and the review before 1.0 checks it:

- A threat model in `docs/security/threat-model.md`, written in 0.3 and updated with every
  release that adds a piece. It covers who's on the network, what each piece can reach, and
  what an attacker gets by taking over each one.
- Least privilege everywhere: every pod hardened, and every ok3d namespace enforcing Kubernetes'
  `restricted` Pod Security Standard. The only exceptions are the pieces that need more (the
  blackbox exporter's `NET_RAW`, istio-cni), each with its reason written next to it.
- Each secret goes from `.env` to its Kubernetes Secret and on to the one piece that uses
  it, and nowhere else. The smoke test's canary secrets check this.
- Supply chain: actions and base images pinned by digest, charts pinned with `Chart.lock`, an
  SBOM and a provenance attestation for every image, and dependency review on every pull
  request.
- Untrusted text, from device names, Wi-Fi network names, logs, and syslog, is marked as such
  everywhere it reaches an agent, and the planted-instruction tests grow with every new path.

**Docs:**

- The structure kia uses: a start-here page, an index, and guides written for someone who has
  never seen ok3d, in plain words and short sentences, saying what to do before why.
- Each subject goes from easy to advanced: the simplest path first, then the options, then
  the advanced parts, then an "under the hood" page that describes the code as it is. An
  under-the-hood page changes in the same pull request as the code it describes.
- The docs job in CI (links, style, the generated settings reference, a runbook per alert,
  the install doc's commands run for real).
- Before each release, the install doc is followed on a fresh test VM exactly as written, and
  anything that had to be guessed gets fixed.

**Pictures in the docs** (decided 2026-10-27). Screenshots and diagrams go wherever they help
someone understand: every Dashboard page, every Grafana dashboard, each step of the install,
and how the pieces fit.

- Diagrams start as Mermaid files in `docs/diagrams/`. `scripts/diagrams.sh` renders each
  one to PNG in `images/diagrams/`, in a light and a dark version at twice the size for sharp
  text, using mermaid-cli from a pinned container image, so it works the same on any machine.
  It records each source's SHA-256 in `images/diagrams/sources.json`, and the docs job fails
  when an image no longer matches its source or has no source.
- Screenshots are made by `scripts/screenshots.sh`, never by hand. It runs on the test VM,
  restored from its clean snapshot first (in CI, on a container running k3d), starts ok3d on
  the simulated network, and drives a headless browser from a pinned container image through the list in
  `docs/screenshots.json` (JSON, since Playwright's image has no YAML library): each page,
  what to wait for, what to crop to, and light or dark.
  It strips the metadata and records the ok3d version each was taken with (making the
  files smaller is still to do: 14 pictures are about 4.7 MB). Docs and releases can then refresh every screenshot in one run.
- The docs show both versions with a `<picture>` tag, so GitHub picks the one for the
  reader's theme. Every image has alt text that says what it shows, and the docs job fails
  on an image without it.
- Every new or changed image is looked at before it's committed, and committed with
  `IMAGES_CHECKED=1`.
- kia's notes for headless browsers apply: use the browser's first tab instead of a new page,
  accept the self-issued certificate, use software rendering so Grafana's graphs draw, and
  wait until Grafana serves the new dashboard before capturing it.

## Roadmap

Each release ends with something that works on its own and a test that proves it, and goes
through the test VM before production. Patch releases (0.4.1, ...) fix what testing and use
turn up. Production moves to ok3d at 0.4.0.

### 0.3: Groundwork

- The repository: the GitHub setup above (workflows added to the `main` ruleset as required
  checks), Renovate, the git hooks, `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, and the
  templates.
- Both chart skeletons (`ok3d-platform` and `ok3d`) with the values schema;
  `settings.example.yaml`, `devices.example.yaml`, and `.env.example`; `.gitignore` for
  every file of your own. Settings carry `settingsVersion: 1` from the start, so later
  migrations know what they're reading.
- `scripts/diagrams.sh` and the first diagrams: how the pieces fit, and the Dashboard-first
  flow.
- The `ok3d` command: `check` (the host check, the schema, a render), `apply` (creates the
  cluster if there isn't one, then both releases), `delete`. One server node, the data root
  mounted into it, kagent's sandbox folder, only the ports in settings published, and the
  Kubernetes API on 127.0.0.1 only. The installer makes the certificate authority.
- Test: `ok3d apply` on a fresh test VM gives an empty, healthy cluster, and `ok3d delete`
  then `ok3d apply` brings it back with the data root untouched.

### 0.4: Metrics, alerts, and a safe front door (production moves here)

- The simulated network and `ok3d demo`, which the smoke test and the screenshots use from
  here on.
- Metrics: kube-prometheus-stack with volumes bound to the data root's folders by label, the
  k3s scrapes off, the blackbox exporter with `icmp` and `NET_RAW`, and unpoller with DPI
  metrics off by default. Probes and scrape targets from `devices.yaml`.
- Alerts reach you: Alertmanager to ntfy and email, and the dead man's switch. Rules for
  devices (down, flapping), the internet link (down, loss, latency, DNS), hosts (disk with
  `predict_linear`, memory, temperature, RAID, SMART), UniFi (device offline, port errors,
  client experience), certificates (expiring), and the NOC watching itself. Each alert links
  to a runbook in `docs/runbooks/`.
- The front door, part one: agentgateway with TLS from the stack's certificate authority,
  security headers, and routes to Grafana (its own login, with a generated password),
  Prometheus, and Alertmanager (both behind basic auth until 0.8). The authority's
  certificate on a download page.
- Retire the old stack: `vars.sh`, the setup script, kgateway, loki-stack, and the old
  manifests go. `docs/upgrading.md` covers the move, which starts fresh (decided
  2026-10-28): old series don't match ok3d's labels, so carrying old Prometheus history or
  Grafana's database is an optional, untested step, and old Loki data can't come across.
- Test: every target in `devices.yaml` shows as up or down, `ok3d test --send-test-alert`
  reaches your phone, nothing answers on the network except through the gateway and syslog,
  and a recreated cluster keeps its history.

### 0.5: The Dashboard (from here, setup starts on a web page)

- The installer (`curl ... | sh`): the host check, the certificate authority, the helper,
  and the Dashboard container. It prints the Dashboard's address, and its password on a
  terminal.
- The Dashboard: the setup cards and choosing parts yourself, settings, write-only secrets,
  the module switches, the Devices page, Check and Apply (Apply stays off until Check finds
  no problems, and keeps the settings from before), and What's next. The action switches
  come with the actions, in 0.9.
- `scripts/screenshots.sh` (moved from 0.4, decided 2026-10-28), with Grafana's dashboards
  and the Dashboard's pages as its first shots, so one script covers both.
- The helper, and its tests for every request it must refuse.
- The Dashboard: a time limit on each whole request, its first line and headers too, not
  only on each read, so a client sending them slowly can't keep a connection (found in the
  review of #30).
- Installing with an AI assistant (decided 2026-10-29): a short prompt to paste into one,
  near the top of the README beside the two commands, and the steps it follows in
  `docs/install-with-ai.md`. It points the assistant at the newest release's copy of that
  page by tag, not main, so the steps match the installer it gets, and has it follow them
  without improvising: list what's missing before installing anything, show each `sudo`
  command and ask first, run the installer, then say where the Dashboard is and where its
  password is kept. It never reads the password or asks for a key (and `./ok3d install`
  prints the password only on a terminal, so it isn't in the assistant's output), and
  stops at the Dashboard, where settings, devices, and keys are set. On an error it
  reports it and stops. Tested with Claude Code on a bare test VM as part of the release test; the docs
  say which assistants it's been tested with.
- Test: from a bare test VM, the installer and the Dashboard alone give the 0.4 stack, with
  no terminal after the installer, and the upgrade from 0.4 works with the installer and the
  Dashboard. The AI prompt does the same on a bare VM (it can be the same install the
  Dashboard-alone run then continues from).

### 0.5.1: The Dashboard's second step (moved from 0.5.0, decided 2026-10-29)

- Upgrades from the Dashboard: back up, move to the new release, check, install, recreate
  (decided 2026-10-29). `./ok3d upgrade vX.Y.Z` does it, run by the helper in a systemd unit
  of its own, since the new release's `./ok3d install` restarts the helper. It takes only a
  newer release whose tag is signed by a key in `deploy/release-signers` (the copy from
  before the move), backs up the settings files, moves back if the new release's check or
  install fails, and backs up `certs/`, `grafana/`, and `alertmanager/` while the cluster is
  down. Looking for a release happens only when you ask (`./ok3d upgrade`, or the button on
  Home), so ok3d still sends nothing on its own.
- Maintenance windows.
- Apply asks first when it would stop something (decided 2026-10-29): Check compares a
  server-side dry run of Apply (`helm upgrade --dry-run=server`, with Apply's own arguments)
  with the deployed release, and lists the workloads that would restart, stop, or start.
  The Dashboard asks before an Apply that restarts or stops anything, or when Check couldn't
  tell; `./ok3d apply` asks on a terminal. The helper's Apply doesn't ask: the Dashboard
  already has.
- Each choice shown as its `ok3d` command (decided 2026-10-29): a muted line on each page
  saying what you'd do on the server instead: `./ok3d check` and `apply` on Home, the file to
  edit on Settings and Devices, the `settings.yaml` lines each setup and switch writes on
  Setup, the `.env` line each key goes into on Keys, and `./ok3d upgrade` on the release pages.
- The Dashboard's screenshots retaken from a release: 0.5.0's show `0.5.0.dev0`, and each page
  now has text they don't (Releases, the commands, what Apply would change).
- Test: 0.5.0 has no upgrade button, so the Dashboard's upgrade is rehearsed on the test VM
  instead, from the Dashboard alone: two local commits of the branch, each with a Dashboard
  image built on the VM and releases fetched from a repository on the VM, the first adding a
  test key to `deploy/release-signers` and the second tagged and signed with it. The
  installer sets up the first, and the Dashboard upgrades it to the second. The upgrade from 0.5.0 to 0.5.1 uses the installer, as before. From 0.5.2,
  each release test is an upgrade from the release before, from the Dashboard alone.

### 0.6: Logs and changes

- Loki with retention, and Alloy's pod logs and syslog (both formats, UDP and TCP), with
  labels for host, app, and severity. Ready configs for UniFi, rsyslog, and Alloy on Linux
  hosts (with their system logs). Log-based alerts: SSH brute force, sudo failures, UniFi
  intrusion prevention events.
- What changed: markers for UniFi configuration changes and firmware updates, deploys and
  upgrades, and new devices.
- New devices: an alert when a device joins the network that isn't in `devices.yaml`, and
  the Dashboard's offer to add it.
- Test: a message in each format over each transport shows up in Grafana, and a new client
  on the test network raises the alert and appears on the Dashboard.

### 0.7: The NOC

- The NOC board: every device as a tile (up, degraded, down), the internet link, active
  alerts, maintenance windows, and recent changes. The UniFi dashboards vendored at a
  pinned revision, with local edits kept as patches applied on top.
- Alerts that know the layout, built from UniFi's uplinks and `devices.yaml`.
- Alerts on targets for the internet link, DNS, Wi-Fi, and the NOC's pages.
- Your internet link: the outage record, the speed test, and the monthly report.
- Digests by ntfy and email.
- Optional modules: Plex, SNMP, and the UPS (NUT).
- Backups: `ok3d backup` on a schedule, to another host or a NAS, and the alerts for stale
  backups, ok3d's and the UniFi controller's.
- `ok3d doctor`: what's wrong, in plain words. `ok3d check-dashboards`: which panels have no
  data on your setup, and why (kia has the same check).
- Test: switching off a test switch gives one alert, not one per device behind it, and a
  restore from backup onto a fresh test VM brings back Grafana, the sign-ins' data, and the
  certificate authority.

### 0.8: Sign-in and the mesh

- Authelia with an admin account and groups, OIDC at the gateway, the user headers, and
  Grafana's role mapping. Prometheus and Alertmanager move from basic auth to sign-in. The
  Dashboard gains sign-in through Authelia, keeping its own password.
- Istio ambient (istiod, istio-cni with k3d's platform setting, and ztunnel) on
  `monitoring`, `gateway`, and `auth`, with mutual TLS required. Waypoints only where
  layer-7 metrics or spans are wanted. AuthorizationPolicies by workload identity, next to
  the NetworkPolicies (which allow the mesh's port, 15008).
- Tempo, with Alloy collecting traces from agentgateway and the waypoints. Traces, logs, and
  metrics linked in Grafana, and Tempo's service graph and request metrics in Prometheus.
- Remote access with Tailscale, optional.
- From kia's front door (kia 0.8.1 didn't start, and an end-to-end test found why): Authelia's
  startup checks fail on a read-only root filesystem, so it never made its database. ok3d
  keeps every pod's root read-only (the charts job and Least privilege, above), so first give
  Authelia writable `emptyDir` folders for the paths it writes; only if that isn't enough,
  name it as an exception there, with its reason. And the gateway can't fetch Authelia's keys
  at its own start (Authelia serves them only for its own name, through the gateway's own
  listener, which isn't up yet), which is one more reason for the local copy in the Sign-in row.
- To weigh when 0.8 starts: bringing LLDAP forward from 1.x, for a Dashboard page to add
  household members, as kia 0.8.3 did. ok3d would never store or check a password (LLDAP
  does), and the helper, never the Dashboard's container, would hold LLDAP's admin login.
- Test: signed out, every page redirects to sign-in; signed in, every page loads, once; a
  page load shows as one trace from the gateway to the app; a pod outside the mesh can't
  reach an app inside it.

### 0.9: Agents and actions

- Decided first (moved from the review before 1.0, 2026-10-29): kagent, or a small page of
  ok3d's own. kia built the proof of concept with kagent, then shipped neither kagent nor its
  sandboxes: a short loop over the Messages API in its Dashboard (standard library only), with
  the model reached through agentgateway, which holds the key and the budget, and only
  read-only tools ("Ask kia", kia 0.8.4; the reasons are in kia's `plans/0.8-kagent-go-no-go.md`:
  an alpha with breaking changes, its own security off by default, no scheduler, and most of
  the value in the tools and the gateway). ok3d already runs the cluster kagent needs, so
  kia's main objection, its weight, counts for less here, though kagent's node alone measured
  1.7 GiB at rest (the host, above); the others hold. Compare the two
  against this release's needs (the chat, the alert explainer, the briefing, the actions), and
  write down the choice before building either.
- If 0.9 chooses kagent: kagent 1.0 behind the front door at `agents.<domain>`, with the
  model route and MCP on the gateway, read-only RBAC, and NetworkPolicies so the sandboxes
  reach only the gateway (not kagent's control plane, which trusts a plain identity header).
  `agents` joins the mesh once gVisor sandboxes are proven to work with ambient's traffic
  redirection.
- The MCP tools: Grafana's (read-only), ok3d's own, UniFi (read), and Plex (read) with its
  module. Remote MCP servers from settings, and `local/` for your own.
- The first agents: one that explains a firing alert (what changed, what the logs say, what
  to check), sent each new critical alert by Alertmanager, with its answer next to the
  alert; and the morning briefing.
- Actions: the Approvals page, the ntfy view action, the action runner, and the first list
  of actions. Plans (tier 3) and the script that applies them.
- Each conversation and each action shows as a trace: the agent, the gateway, the model
  call, each tool call, and the action.
- Defenses against planted instructions, in this order (from kia's review of its own agents
  plan): no tool that changes anything outside the action runner; no tool that fetches an
  address it's given; answers shown as plain text, with no image or link loaded by itself (an
  image can carry data out); never a command that isn't in ok3d's docs; a token cap per
  request and a rate limit per key at the gateway; and a limit on tool rounds in the agent's
  own loop, since the gateway can't cap a whole conversation. Together they stop text that
  makes an agent loop from running up a bill.
- Each tool is allowed by its exact operation, never a settings or configuration call: UniFi's
  WLAN configuration, for one, returns each network's Wi-Fi passphrase. No tool's
  answer passes on an address from a metric label. A test runs every tool against fixtures
  holding known secret values and checks none of them comes back (kia's review asked for the
  same).
- Whatever reads strangers' text (logs, device and Wi-Fi names, syslog) holds only the
  read-only key it needs: never one that writes, the model's key, or another tool's key.
- Test: a planted instruction in a log line, a device name, or a Wi-Fi network name doesn't
  change what the agent does or asks for; an answer shows as plain text, with no image or
  link loaded by itself; no command outside ok3d's docs is suggested; the token cap, the rate
  limit, and the tool-round limit stop a looping agent; an action without approval doesn't
  run; a protected device can't be touched even with approval.

### The review before 1.0

When 0.9 is feature-complete, nothing new goes in until two reviews are done and their
findings are fixed or written down as decided.

**A full independent review, of every file, with no spot checks.** Every script, template,
values file, rule, dashboard, workflow, test, and doc, read in full. For each: is it
correct, is it tested, is it secure, is it documented, and does it match what the docs say?
Every alert rule is checked against the metrics that actually exist (the mistake that kept
the old UniFi rules from ever firing). Every finding is written up with where it is, what's
wrong, and how it fails.

**An architectural review, asking why.** For each choice in the decisions table, whether it
still holds with what we know at the end of 0.9:

- Is this the best way to build it? k3d on one server; Helm as two releases; the Dashboard
  outside the cluster with a helper; agentgateway north/south and Istio east/west (is the
  mesh paying for itself at home scale?); whichever 0.9 chose, kagent or ok3d's own page,
  looked at again with 0.9 built; one server node.
- Can it be more secure? A written threat model: who's on the network, what each piece can
  reach, and what an attacker gets from taking over each one (the Dashboard's container,
  the helper's requests, the gateway, an agent's sandbox, a device sending syslog). Fuzzing
  the helper's requests; a test of the front door from the network; prompt-injection tests
  through every way text reaches an agent; the actions' guardrails under attack; images
  scanned and their provenance checked; secrets never in logs, traces, or the page.
- What would we do differently now? Pieces that turned out heavier than they're worth;
  pieces that should be one; anything we'd drop; anything the users and the test VM runs
  kept tripping on.
- Is it easy enough? Someone who has never seen ok3d installs it on a fresh VM from the docs
  alone, and we note every place they had to guess.
- Can it last? The upgrade path from every 0.9 release, settings that will stay compatible
  through 1.x, and the effort to keep every pinned version current.

The results go in `docs/reviews/1.0-review.md`. Then a 1.0.0 release candidate runs on the
test VM and in production for at least two weeks with no critical finding before 1.0.0.

### 1.0: Stable

What 1.0 promises: settings that stay compatible through 1.x (a change that needs your
attention comes with a migration the Dashboard runs and explains), an upgrade from every 1.x
release, docs a newcomer can install from, and security fixes for the latest release.

### 1.x

- **1.1: Public certificates.** `tls.mode: public`: Let's Encrypt through cert-manager with
  a DNS-01 challenge, so nothing has to be reachable from the internet, on Let's Encrypt's
  staging server until you switch to production. If cert-manager supports your DNS provider
  (Cloudflare, Route53, Google, Azure, DigitalOcean, RFC2136, and others), it updates your
  zone directly. If not (cPanel hosting and many registrars), you add one CNAME at your
  provider, `_acme-challenge.<domain>`, pointing into a zone at a supported provider, and
  cert-manager follows it (`cnameStrategy: Follow`); the cluster's key can then edit only
  that zone, never your real DNS, email, or website. The certificate and the ACME account
  key are kept in the data root and restored on each new cluster, so recreating it doesn't
  hit Let's Encrypt's rate limits. The Dashboard checks for CAA records that would block
  Let's Encrypt.
- **The second list of actions:** block or unblock a client, and run a speed test now.
- **LLDAP** behind Authelia, for household accounts managed on a page.
- **An optional GitOps mode** (Argo CD or Flux) for settings kept in a private repository,
  if people ask for it.

## Docs

Written for someone who has never seen the project, in plain words, with diagrams made from
Mermaid files:

- `README.md`: what it is, what it shows, and what you need.
- `docs/install.md`: from a bare Linux server to alerts on your phone: the data root (with
  LVM), local DNS, the installer, the Dashboard, the first apply, trusting the certificate
  authority, and the first test alert.
- `docs/dashboard.md`: every page of the Dashboard, and the `ok3d` command each one equals.
- `docs/settings.md`: every setting, generated from the values schema so it can't drift.
- `docs/devices.md`: adding devices, protected devices, and what each check does.
- `docs/alerts.md`: every alert, what it means, and where it's sent.
- `docs/runbooks/`: one page per alert: what to check, in order.
- `docs/sign-in.md`: accounts, groups, roles, and second factors.
- `docs/agents.md`: what the agents can and can't do, the actions and their guardrails,
  approvals, and what the agents cost.
- `docs/upgrading.md`: upgrading from the Dashboard, what's backed up first, and moving from
  the old stack.
- `docs/architecture.md`: how the pieces fit, and why each choice was made.
- `docs/troubleshooting.md`.
- `docs/setups.md`: each setup card, what it gives you, and the hardware it needs.
- `docs/certificate.md`: why the browser warns before you trust ok3d's certificate authority,
  and how to stop it on each kind of device (kia's `secure-page.md` covers the same).
- `docs/metrics.md`: every metric ok3d's own parts expose.
- `docs/demo.md`: trying ok3d on the simulated network.
- Under-the-hood pages: the Dashboard and the helper, security, the network's layout and how
  alerts are held back, and the agents and actions.

## To check before building

- agentgateway: does it reload a renewed certificate when the mounted Secret changes, or does
  it need a restart (0.4)? kia found its listener certificate and backend root reload by
  themselves from mounted files (Compose, v1.6.0), but on Docker Desktop the gateway noticed
  the first new file and missed later ones. A Secret's mount updates by swapping a link,
  which is a rename too, so check more than one renewal in a row. Two traps kia hit: rustls
  refuses a certificate from plain `openssl req -x509` as a server certificate, since it's
  marked as a CA, and macOS LibreSSL's `openssl req -newkey ec` test keys gave a key
  mismatch.
- agentgateway's model route (0.9), from kia's 0.8.4: use its Anthropic provider directly,
  since the OpenAI-to-Anthropic translation passes `arguments: null` through for a tool call
  with no arguments, and Anthropic answers 400. A budget in dollars needs agentgateway's
  standalone mode and a database that survives restarts (SQLite is enough, in a folder its
  user, uid 65532, can write: `gateway/` in the data root). It attaches only to a fixed key
  (one budget per key, not per person), is charged after each answer (so one request can run
  past it), and answers 429 with `budget_exceeded` once it's spent. With no price set for the
  model, the budget stays at zero and never refuses anything. Prompt cache reads are billed
  at cache rates.
- cert-manager: does a CA Issuer built from the installer's authority keep issuing from it
  in each new cluster (0.4)? Does it adopt a restored Let's Encrypt certificate without
  issuing again? Test against staging, keeping the annotations it writes (1.1).
- agentgateway: confirm there's no UDP listener, which is why syslog has its own Service
  (0.6).
- unpoller: how many series a typical home produces with DPI on and off, to set the default
  (0.4).
- The Dashboard and the helper: how the Dashboard's container writes requests into its
  folder without being able to read anything else in the data root, and how the helper runs
  on a host without systemd user services (0.5).
- Alloy: the minimum version that reads RFC3164 syslog, and how it labels UniFi's messages
  (0.6).
- UniFi: what the official Network Integration API can report (uplinks for the layout,
  configuration changes, new clients) and do (each action on the first list), and what
  needs the older controller API (0.6, 0.7, 0.9).
- agentgateway with Authelia inside the cluster: does the token exchange need its own
  listener to set the forwarded headers, as in kia's proof of concept? How does the local
  copy of Authelia's keys get refreshed when they rotate (0.8)? kia makes Authelia's signing
  key itself and writes the public half to a file, so there's no fetch, and a refresh is
  needed only when kia rotates the key; ok3d can do the same.
- Grafana: mapping a role from a gateway header, or Grafana's own OIDC against Authelia if
  the header can't carry the role (0.8).
- Istio ambient on k3d: the install with k3d's platform setting, ztunnel and istio-cni with
  k3s's CNI paths, and the NetworkPolicies with the mesh's port (0.8).
- kagent 1.0: the GA version, whether GA changes the install or the resources, and which
  packaged agents 1.0 ships (0.9).
- Istio ambient and kagent's gVisor sandboxes: does ambient's traffic redirection inside the
  pod catch traffic from gVisor's own network stack? Until it's proven, `agents` stays out
  of the mesh (0.9).
- ntfy: whether a view action can open a page behind sign-in on a phone cleanly, on iOS and
  Android (0.9).
- cert-manager: the CNAME-delegated challenge end to end, with a wildcard and the bare name
  in one certificate, both validated through the one delegated `_acme-challenge` name (1.1).
