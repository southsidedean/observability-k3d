# Security

ok3d watches your home network, so it can see a lot of it: devices, logs, and what's
connected where. This page says how to report a problem and how ok3d is built to limit the
damage if something goes wrong.

## Reporting a problem

Please report security problems privately, through GitHub: on the repository's **Security**
tab, choose **Report a vulnerability**, or use
[this link](https://github.com/southsidedean/observability-k3d/security/advisories/new).
Please don't open a public issue.

Say what the problem is, how to reproduce it, and which version you use.

## Supported versions

Fixes go into the latest release. `v0.2.0`, the old stack, gets no fixes: the rebuild replaces
it in 0.4, and its known problems are listed in its release notes and in [PLAN.md](PLAN.md).

## Your data stays home

ok3d has no telemetry. It sends nothing anywhere except what you set up yourself: alerts to
ntfy or email, the dead man's switch, calls to the AI model, and backups.

## How ok3d limits the damage

ok3d is being rebuilt, and each release adds its part of the following. [PLAN.md](PLAN.md)
has the details and the threat model's place in each release.

- **One way in.** Every web page is reached through one gateway, over TLS, behind a sign-in.
  Nothing else in the cluster answers on your network except the syslog listener.
- **Least privilege.** Every pod runs as a non-root user with a read-only filesystem and no
  extra capabilities, under Kubernetes' `restricted` Pod Security Standard. The few
  exceptions (the ping checks need `NET_RAW`) say why next to them.
- **Secrets stay where they're used.** Each secret goes from `.env` to the one piece that
  uses it. The Dashboard sets secrets but never shows them back. Tests check that no secret
  reaches a log, a trace, a page, or an alert.
- **The Dashboard can't run anything itself.** It asks a helper on the host, which accepts
  only a short list of requests and checks each one again.
- **Agents read; people decide.** Agents can only read, except for a short list of safe
  actions that each need a signed-in person's approval. Nothing an agent reads (a device
  name, a log line) can give it a way to change your firewall, VLANs, routing, or
  credentials: no tool for those exists.
- **A checked supply chain.** Actions and base images are pinned by digest, every image is
  scanned before it's published, and every published image has an SBOM and a record of how
  it was built.
