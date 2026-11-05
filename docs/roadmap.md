# Roadmap

Where ok3d is, release by release. Every pull request updates this page when it finishes,
starts, or changes something here. [PLAN.md](../PLAN.md#roadmap) has the detail of each
release and the reasons behind it.

**Now:** 0.5.2 is released. 0.5.3 is in progress: fixes for what 0.5.2's release test found.
0.6.0, logs and changes, comes next.

| Release | What it brings | Status |
|---|---|---|
| 0.2.0 | The old stack's last version | Released ([v0.2.0](https://github.com/southsidedean/observability-k3d/tree/v0.2.0)) |
| 0.3.0 | Groundwork: CI, hooks, tests, the charts, the `ok3d` command, the certificate authority | Released ([v0.3.0](https://github.com/southsidedean/observability-k3d/releases/tag/v0.3.0)) |
| 0.4.0 | Metrics, alerts that reach you, and a safe front door | Released ([v0.4.0](https://github.com/southsidedean/observability-k3d/releases/tag/v0.4.0)) |
| 0.5.0 | The Dashboard: set up and change ok3d from a web page, and screenshots in the docs | Released ([v0.5.0](https://github.com/southsidedean/observability-k3d/releases/tag/v0.5.0)) |
| 0.5.1 | The Dashboard's second step: upgrades, maintenance windows, and Apply asking first | Released ([v0.5.1](https://github.com/southsidedean/observability-k3d/releases/tag/v0.5.1)) |
| 0.5.2 | Small fixes from 0.5.1, and the first release test that upgrades from the Dashboard alone | Released ([v0.5.2](https://github.com/southsidedean/observability-k3d/releases/tag/v0.5.2)) |
| 0.5.3 | Fixes for what 0.5.2's release test found: maintenance windows kept through an upgrade, and Apply recovering from a restart partway | In progress |
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
| Move production to ok3d: its server has a 0.4.0 checkout but no cluster yet, so it moves straight to the latest release | Planned |

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
| Upgrades from the Dashboard: back up, move to the new release, check, install, and recreate (`./ok3d upgrade`, signed releases only) | Done ([#42](https://github.com/southsidedean/observability-k3d/pull/42)) |
| Maintenance windows | Done ([#45](https://github.com/southsidedean/observability-k3d/pull/45)) |
| Apply asks first when it would stop something | Done ([#43](https://github.com/southsidedean/observability-k3d/pull/43)) |
| Each choice shown as its `ok3d` command | Done ([#44](https://github.com/southsidedean/observability-k3d/pull/44)) |
| The Dashboard's screenshots retaken, showing a released version and each page's new text | Done ([#47](https://github.com/southsidedean/observability-k3d/pull/47)) |
| Release 0.5.1 ([#47](https://github.com/southsidedean/observability-k3d/pull/47)): the installer from 0.5.0, and the Dashboard's upgrade rehearsed with a test tag (0.5.0 has no Upgrade button) | Done |

## 0.5.2, in detail

| Part | Status |
|---|---|
| The Maintenance page says it hasn't read Alertmanager yet, instead of "No maintenance windows" | Done ([#49](https://github.com/southsidedean/observability-k3d/pull/49)) |
| The Maintenance page says when lines in the helper's note can't be read, instead of "No maintenance windows" | Done ([#51](https://github.com/southsidedean/observability-k3d/pull/51)) |
| Check said the upgrade from 0.5.0 would restart the gateway, and it didn't: Check counted the chart's label as a restart, and now counts only a changed pod template or replica count | Done ([#50](https://github.com/southsidedean/observability-k3d/pull/50)) |
| A social image for GitHub, with its source in `images/` | Done ([#52](https://github.com/southsidedean/observability-k3d/pull/52)) |
| The social image says ok3d is self-contained, in its own k3d cluster | Done ([#56](https://github.com/southsidedean/observability-k3d/pull/56)) |
| Fixes from the 0.5.2 review: the charts and alerts | Done ([#53](https://github.com/southsidedean/observability-k3d/pull/53)) |
| Fixes from the 0.5.2 review: the shell, the installer, and the git hooks | Done ([#54](https://github.com/southsidedean/observability-k3d/pull/54)) |
| Fixes from the 0.5.2 review: the Dashboard, the helper, and maintenance windows | Done ([#55](https://github.com/southsidedean/observability-k3d/pull/55)) |
| Fixes from the 0.5.2 review: the UniFi dashboards' panel descriptions, plugins, and upstream text | Done ([#58](https://github.com/southsidedean/observability-k3d/pull/58)) |
| Fixes from the 0.5.2 review: the docs, `PLAN.md`, and `SECURITY.md` | Done ([#57](https://github.com/southsidedean/observability-k3d/pull/57)) |
| Fixes from the 0.5.2 test VM pass: the gateway's login speed, the dead man's switch's pace, the memory figure | Done ([#59](https://github.com/southsidedean/observability-k3d/pull/59)) |
| Release 0.5.2 ([#60](https://github.com/southsidedean/observability-k3d/pull/60)), tested with an upgrade from 0.5.1 from the Dashboard alone | Done |

## 0.5.3, in detail

| Part | Status |
|---|---|
| A maintenance window added or changed in the 15 minutes before an upgrade comes through: Alertmanager is stopped cleanly, so it saves its silences, before the cluster is deleted | Planned |
| After a restart partway through an upgrade, Check and Apply on the Dashboard finish it, instead of Apply failing on Helm's unfinished release | Planned |
| The upgrade's output on Home without k3d's color codes, and the steps for going back that work without a `.env` | Planned |
| The steps from 0.5.0 or 0.4, tested from the 0.4.0 snapshot, and the screenshots retaken to show a released version | Planned |
| Release 0.5.3, tested with an upgrade from 0.5.2 from the Dashboard alone, with a maintenance window added just before and a restart partway | Planned |

## Found in the 0.5.2 review, for later

The full review before 0.5.2 found these. Each is too big for a patch release, so each waits
for the release named, or for a decision.

| Part | When |
|---|---|
| Alerts held back per problem, not per device: a full disk shouldn't hold back the same computer's memory warning | 0.7, with the alerts that know the layout |
| An alert when unpoller has no target at all (its pod never ready), not only when the controller doesn't answer | 0.7 |
| cert-manager's metrics scraped, so a certificate it fails to renew raises an alert | 0.6 |
| NetworkPolicies for cert-manager and kube-system, and between monitoring's own parts | 0.8, with the mesh |
| A warning when a silence made on Alertmanager's own page covers the Watchdog | 0.7 |
| The Dashboard's sign-in pause, which any device on the network can keep on for everyone by guessing, and its 32 connections, which one device can fill: limits per address instead | 0.8, with the new sign-in |
| Prometheus's and Alertmanager's basic auth doesn't limit wrong passwords (so a password you choose must be long, and Check warns about a short one): the new sign-in replaces it | 0.8, with the new sign-in |
| The NOC with agents setup card can't be chosen: it needs `modules.agents`, which only the server may change. Decide how the Dashboard turns agents on, and say so on the card | 0.9 |
