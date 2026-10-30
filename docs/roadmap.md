# Roadmap

Where ok3d is, release by release. Every pull request updates this page when it finishes,
starts, or changes something here. [PLAN.md](../PLAN.md#roadmap) has the detail of each
release and the reasons behind it.

**Now:** 0.5.0 is released. 0.5.1 is in progress: the Dashboard's second step.

| Release | What it brings | Status |
|---|---|---|
| 0.2.0 | The old stack's last version | Released ([v0.2.0](https://github.com/southsidedean/observability-k3d/tree/v0.2.0)) |
| 0.3.0 | Groundwork: CI, hooks, tests, the charts, the `ok3d` command, the certificate authority | Released ([v0.3.0](https://github.com/southsidedean/observability-k3d/releases/tag/v0.3.0)) |
| 0.4.0 | Metrics, alerts that reach you, and a safe front door | Released ([v0.4.0](https://github.com/southsidedean/observability-k3d/releases/tag/v0.4.0)) |
| 0.5.0 | The Dashboard: set up and change ok3d from a web page, and screenshots in the docs | Released ([v0.5.0](https://github.com/southsidedean/observability-k3d/releases/tag/v0.5.0)) |
| 0.5.1 | The Dashboard's second step: upgrades, maintenance windows, and Apply asking first | In progress |
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
| NetworkPolicies: inside the cluster, each part accepts only what it should | Done ([#16](https://github.com/southsidedean/observability-k3d/pull/16)) |
| Screenshots of the pages for the docs (`scripts/screenshots.sh` on the test VM) | Moved to 0.5 |
| Retire the old stack, and the guide for moving from it | Done ([#17](https://github.com/southsidedean/observability-k3d/pull/17)) |
| Release 0.4.0 ([#18](https://github.com/southsidedean/observability-k3d/pull/18)), installed on the test VM from its base snapshot | Done |
| Move production to 0.4.0 | In progress |

## 0.5.0, in detail

| Part | Status |
|---|---|
| The helper: runs `./ok3d check` and `apply` for the Dashboard, and refuses everything else | Done ([#21](https://github.com/southsidedean/observability-k3d/pull/21)) |
| The Dashboard's image, and the workflow that builds, scans, and publishes it, with its sign-in and first page | Done ([#22](https://github.com/southsidedean/observability-k3d/pull/22)) |
| The helper saves settings, devices, and secrets for the Dashboard, after `./ok3d validate` checks them | Done ([#23](https://github.com/southsidedean/observability-k3d/pull/23)) |
| The Dashboard's pages: settings, write-only secrets, devices, Check and Apply | Done ([#24](https://github.com/southsidedean/observability-k3d/pull/24)) |
| The installer (`curl ... \| sh`): the host check, the helper's service, the Dashboard | Done ([#25](https://github.com/southsidedean/observability-k3d/pull/25)) |
| The Dashboard's setup cards, module switches, and What's next | Done ([#27](https://github.com/southsidedean/observability-k3d/pull/27)) |
| Screenshots of the pages for the docs (`scripts/screenshots.sh` on the test VM) | Done ([#29](https://github.com/southsidedean/observability-k3d/pull/29)) |
| The Dashboard answers every refused form, and every form has a time limit | Done ([#30](https://github.com/southsidedean/observability-k3d/pull/30)) |
| A time limit on each whole request to the Dashboard, its headers too | Done ([#32](https://github.com/southsidedean/observability-k3d/pull/32)) |
| Installing with an AI assistant: a prompt to paste into one, offered near the top of the README | Done ([#33](https://github.com/southsidedean/observability-k3d/pull/33)) |
| Upgrades from the Dashboard, maintenance windows, Apply asking first, and each choice's command | Moved to 0.5.1 |
| Release 0.5.0 ([#40](https://github.com/southsidedean/observability-k3d/pull/40)), tested from a bare test VM with the installer and the Dashboard alone, the AI prompt, and the upgrade from 0.4 | Done |

## 0.5.1, in detail

| Part | Status |
|---|---|
| Upgrades from the Dashboard: back up, move to the new release, recreate, and check (`./ok3d upgrade`, signed releases only) | Done ([#42](https://github.com/southsidedean/observability-k3d/pull/42)) |
| Maintenance windows | Done ([#45](https://github.com/southsidedean/observability-k3d/pull/45)) |
| Apply asks first when it would stop something | Done ([#43](https://github.com/southsidedean/observability-k3d/pull/43)) |
| Each choice shown as its `ok3d` command | Done ([#44](https://github.com/southsidedean/observability-k3d/pull/44)) |
| The Dashboard's screenshots retaken, showing a released version and each page's new text | Planned |
| Release 0.5.1: the installer from 0.5.0, and the Dashboard's upgrade rehearsed with a test tag (0.5.0 has no Upgrade button) | Planned |
