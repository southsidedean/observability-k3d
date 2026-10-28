# Changelog

## 0.4.0 (unreleased)

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
