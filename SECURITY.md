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
ntfy or email, the dead man's switch, calls to the AI model, and backups. It looks for a new
release (asking GitHub for the list) only when you ask it to, with **Look for a new release**
on the Dashboard or `./ok3d upgrade` on the server.

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
  only a short list of requests and checks each one again
  ([how](docs/helper-under-the-hood.md)).
- **Agents read; people decide.** Agents can only read, except for a short list of safe
  actions that each need a signed-in person's approval. Nothing an agent reads (a device
  name, a log line) can give it a way to change your firewall, VLANs, routing, or
  credentials: no tool for those exists.
- **A checked supply chain.** Actions and base images are pinned by digest, every image is
  scanned before it's published, and every published image has an SBOM and a record of how
  it was built.

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
  days each, set now or up to a year ahead, and end ok3d's own windows (never a silence made some other way). Home shows a
  red line while a window is on, and `./ok3d maintenance` on the server lists them.
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
- Every request it takes gets an answer, from a fixed list, that repeats nothing from the
  request but a valid id.
- It runs one request at a time, with a time limit, and a second helper won't start. An
  upgrade has no time limit (making the cluster again can take as long as a first Apply),
  and while one runs the helper takes no request at all.
- An upgrade moves only forward, and only to a release whose tag is signed with ok3d's
  release key (`deploy/release-signers`, as your copy has it before the move) and named
  for the release it is. Anyone who could push a tag to ok3d's repository without that key
  still can't move you to their code, or back to an older release.

These hold only when the Dashboard's container gets the outbox read-write on its own, the
helper's folder read-only, and runs as you. The installer sets it up that way
([details](docs/helper-under-the-hood.md#what-the-dashboards-container-must-be-given)).

Tests in `tests/test_helper.py` send it every kind of bad request, swap its folders for
links, and send folders built to make removing them fail, and Hypothesis sends it random
bytes, to check that only a valid request ever runs anything and the next one still works.
