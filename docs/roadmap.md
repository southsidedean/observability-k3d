# Roadmap

Where ok3d is, release by release. Every pull request updates this page when it finishes,
starts, or changes something here. [PLAN.md](../PLAN.md#roadmap) has the detail of each
release and the reasons behind it.

**Now:** 0.4.0 is in progress. Production moves to ok3d when 0.4.0 is released.

| Release | What it brings | Status |
|---|---|---|
| 0.2.0 | The old stack's last version | Released ([v0.2.0](https://github.com/southsidedean/observability-k3d/tree/v0.2.0)) |
| 0.3.0 | Groundwork: CI, hooks, tests, the charts, the `ok3d` command, the certificate authority | Released ([v0.3.0](https://github.com/southsidedean/observability-k3d/releases/tag/v0.3.0)) |
| 0.4.0 | Metrics, alerts that reach you, and a safe front door | In progress |
| 0.5.0 | The Dashboard: set up and change ok3d from a web page | Planned |
| 0.6.0 | Logs and changes: syslog, host logs, what-changed markers, new devices | Planned |
| 0.7.0 | The NOC: the board, alerts that know the layout, the internet link's record, backups | Planned |
| 0.8.0 | One sign-in for every page, the mesh, and traces | Planned |
| 0.9.0 | Agents and actions, with your approval | Planned |
| Review | A full independent review and an architectural review, before 1.0 | Planned |
| 1.0.0 | Stable: settings that stay compatible through 1.x | Planned |
| 1.1.0 | Public certificates from Let's Encrypt | Planned |

## 0.4.0, in detail

| Part | Status |
|---|---|
| The simulated network (`./ok3d demo`) | Done ([#12](https://github.com/southsidedean/observability-k3d/pull/12)) |
| Metrics: Prometheus with its history in the data root, checks for every device, UniFi | Done ([#13](https://github.com/southsidedean/observability-k3d/pull/13)) |
| Alerts to ntfy and email, the dead man's switch, 12 tested rules with runbooks | Done ([#14](https://github.com/southsidedean/observability-k3d/pull/14)) |
| The front door: HTTPS through agentgateway, Grafana and its dashboards, one admin login, the certificate download | Done ([#15](https://github.com/southsidedean/observability-k3d/pull/15)) |
| NetworkPolicies: inside the cluster, each part accepts only what it should | In progress |
| Screenshots of the pages for the docs (`scripts/screenshots.sh` on the test VM) | Planned |
| Retire the old stack, and the guide for moving from it | In progress |
| Release 0.4.0, install it on the test VM, then move production to it | Planned |
