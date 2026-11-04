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

Fixes go into the latest release. `v0.2.0`, the old stack, gets no fixes: 0.4 replaced it, and
its known problems are listed in its release notes and in [PLAN.md](PLAN.md).

## Your data stays home

ok3d has no telemetry. It sends nothing anywhere except what you set up yourself: alerts to
ntfy or email, the dead man's switch, calls to the AI model, and backups. It looks for a new
release (asking GitHub for the list) only when you ask it to, with **Look for a new release**
on the Dashboard or `./ok3d upgrade` on the server.

## How ok3d limits the damage

ok3d is built release by release, so some of this holds now and some comes later; each item
says which. [PLAN.md](PLAN.md) has the details. A threat model, planned for 0.3, isn't
written yet: it's due before 1.0, with the architectural review.

- Every page in the cluster is reached through one gateway, over TLS (now). Grafana,
  Prometheus, and Alertmanager need the admin login, and one sign-in covers all of them from
  0.8; the certificate authority's download page needs none. Nothing else in the cluster
  answers on your network (from 0.6, the syslog listener will too). The Dashboard runs
  outside the cluster, over its own HTTPS, with its own password.
- Every pod runs as a non-root user with a read-only filesystem and no capabilities, under
  Kubernetes' `restricted` Pod Security Standard (now). Ping works without `NET_RAW`, through
  Linux's unprivileged ping. The only exception expected is istio-cni (0.8), which will say
  why next to it.
- Each secret goes from `.env` to the one piece that uses it, and the Dashboard sets secrets
  but never shows them back (now). Tests that check no secret reaches a log, a trace, a page,
  or an alert come with the end-to-end smoke test (planned).
- The Dashboard can't run anything itself (now). It asks a helper on the host, which accepts
  only a short list of requests and checks each one again
  ([how](docs/helper-under-the-hood.md)).
- Agents can only read, except for a short list of safe actions that each need a signed-in
  person's approval (from 0.9). Nothing an agent reads (a device name, a log line) can give
  it a way to change your firewall, VLANs, routing, or credentials: no tool for those
  exists.
- Actions are pinned by commit, and the Dashboard's base image is resolved to one digest per
  build, so the image scanned is the image pushed (now). Every image is scanned before it's
  published, and every published image has an SBOM and a record of how it was built.

## The helper

The helper (`src/ok3d/helper.py`) runs on the server as you, and carries out requests the
Dashboard leaves in `<data root>/dashboard/outbox/`. It's written for the case where the
Dashboard's container has been taken over:

- It opens its folders once, refusing links and folders that belong to someone else, and
  works through those handles from then on, so a folder swapped for a link later leads
  nowhere.
- It renames each request into its own folder, under a new name each time, before opening
  anything, so a link moves as a link and is never followed. It refuses links, hard links,
  folders, and pipes, and never removes a folder someone sent it.
- It reads at most 65 KB and accepts a fixed set of fields. The only commands it runs are
  `./ok3d check`, `./ok3d apply`, `./ok3d validate` on a file in its own folder, and
  `./ok3d upgrade`, either with nothing after it (to look for a release) or, started with
  `systemd-run` as a service of its own, with the one argument a request may carry: a
  release, checked to be `v` and three numbers. It also runs `./ok3d maintenance` with a
  window's lines, each checked whole (all or device names, a length or two times, a short
  plain reason, or a window's id), and asks `systemctl` whether an upgrade is running.
- A maintenance window never silences the dead man's switch, so even a window for all of
  ok3d, set from a Dashboard someone has taken over, can't hide ok3d stopping. Such a
  Dashboard could still keep every other alert quiet, with up to 20 windows of at most 30
  days each, set now or up to a year ahead, and end ok3d's own windows (never a silence
  made some other way). Home shows a red line while a window is on, and `./ok3d maintenance`
  on the server lists them.
- It saves a settings or devices file only after `./ok3d validate` passes it, keeping a
  copy of the old one. A file from the Dashboard may hold only your own settings or devices,
  never the chart's own sections, and may not change where ok3d keeps its data or where it
  sends your keys, tokens, and passwords (the UniFi controller, the ntfy server, the mail
  server), or turn on remote access, the mesh, or agents; those you change on the server.
  Until you've made `settings.yaml` on the server, the Dashboard can't save settings at all.
- It sets only four lines of `.env` (the UniFi key, the ntfy topic and token, and the mail
  password), one plain-text line at a time, and never sends a value back: copies of `.env`
  go to `local/backups/` in the ok3d checkout, which the Dashboard can't see. The admin
  password, the AI model's key, and the dead man's switch's address are yours alone to set,
  on the server.
- `./ok3d` itself refuses a `settings.yaml` or `devices.yaml` that holds the chart's own
  sections, which choose images and how pods run, whoever wrote it.
- The Dashboard may still change who receives alerts (an email address, the ntfy topic).
  Alerts name your devices and what's wrong with them, but carry no keys or passwords.
- It refuses requests older than 5 minutes, and any of the last 100 ids it carried out.
- Every request it takes gets an answer. A refused one's answer gives a reason from a fixed
  list and repeats nothing from the request but a valid id; any other answer also names its
  action (and, for a `.env` line, its name), both checked against fixed lists first.
- It runs one request at a time, with a time limit, and a second helper won't start. An
  upgrade has no time limit (making the cluster again can take as long as a first Apply),
  and while one runs the helper takes no request at all.
- An upgrade moves only forward, and only to a release whose tag is signed with ok3d's
  release key (`deploy/release-signers`, as your copy has it before the move) and named
  for the release it is. Anyone who could push a tag to ok3d's repository without that key
  still can't move you to their code, or back to an older release.

These hold only when the Dashboard's container gets its own folder (`dashboard/`, which
holds the outbox) read-write, the helper's folder read-only, and nothing else of the data
root, and runs as you. The installer sets it up that way
([details](docs/helper-under-the-hood.md#what-the-dashboards-container-must-be-given)).

Tests in `tests/test_helper.py` send it every kind of bad request, swap its folders for
links, and send folders built to make removing them fail, and Hypothesis sends it random
bytes, to check that only a valid request ever runs anything and the next one still works.
