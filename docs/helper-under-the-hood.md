# The helper under the hood

How a click on the Dashboard's **Check** or **Apply** becomes `./ok3d check` or `./ok3d apply`
on the server, how a change you save on the Dashboard reaches `settings.yaml`,
`devices.yaml`, or `.env`, and how an upgrade starts. This page describes the code as it is,
in `src/ok3d/helper.py`.

## Why there's a helper

The Dashboard runs in a container. To make the cluster, it would need Docker, and access to
Docker is as good as full control of the server. So the Dashboard gets no Docker and can't
run anything itself. It leaves a request in a file instead, and the helper, a small service
running on the server as you, carries it out.

The helper assumes someone may have taken over the Dashboard's container. The most they can
do through it is run `./ok3d check` or `./ok3d apply`, change the settings the Dashboard is
allowed to change, change your devices, set four lines of `.env`, or move ok3d to a newer
release that's signed with ok3d's release key. They can't change where
ok3d keeps its data, where it sends your keys, tokens, and passwords, or how far it's open to
the outside; can't reach the chart's own sections (which choose images and how pods run);
can't choose the admin password; and can't read a secret back.

## The pieces

| Piece | Where | What it does |
|---|---|---|
| The outbox | `<data root>/dashboard/outbox/` | The Dashboard writes its request here, as `request` |
| The helper's folder | `<data root>/helper/` | Only the helper writes here; the Dashboard can read it |
| Taken requests | `<data root>/helper/taken/` | Where each request is moved before it's read |
| `src/ok3d/helper.py` | the ok3d checkout | The helper itself: standard library only, run with the server's own Python |
| `deploy/ok3d-helper.service` | `~/.config/systemd/user/` | Runs the helper as a systemd user service, as you |

When it starts, the helper makes the folders if they're missing, opens each one, and sets
them readable only by you. It refuses to start if one is a link or belongs to someone else.
From then on it works through the folders it opened, never through their paths again, so a
folder the Dashboard swaps for a link later leads nowhere.

### What the Dashboard's container must be given

The helper's checks hold only with the right mounts, which the installer sets up:

- `dashboard/outbox/` mounted read-write on its own, not the data root or anything above the
  outbox's parent, so the container can't reach the helper's folder through a request it
  sent.
- `helper/` mounted read-only, so it can read answers but never write one.
- The container runs as you, so it can read the helper's answers, which are readable only
  by you.

## A request, from click to answer

1. You press **Check** or **Apply**. The Dashboard writes `dashboard/outbox/request`:

   ```ini
   id=3f9a0c51d2e8b746
   action=check
   ```

   The id is a random number the page makes, so it knows which answer is to its own request.
2. Every 3 seconds, the helper renames that file into `helper/taken/`, under a name that's
   new each time, so nothing left from before is ever in the way. A rename moves whatever is
   there: a link moves as a link, never what it points to.
3. It checks what arrived, and refuses it without running anything unless all of these hold:
   - It's a plain file, not a link, a folder, or a pipe, and not a hard link to another file.
   - It's at most 65 KB.
   - It was written in the last 5 minutes (or up to a minute ahead, for a clock that's off).
   - Its head is plain ASCII text, with each line ending in a newline.
   - Its head has exactly the lines its action needs, each once, and nothing else: `id` and
     `action`, `name` with `set-env`, `version` with `upgrade`, and optionally `base` with a
     save.
   - The id is 16 to 64 lowercase hex digits.
   - The action is one of `check`, `apply`, `save-settings`, `save-devices`, `set-env`,
     `look-for-release`, or `upgrade`, exactly. A save and `set-env` have a blank line and
     then a body (below); the others have nothing after their head.
   - The id isn't one of the last 100 the helper carried out, so a request can't be replayed.
   - No upgrade is running (below): while one is, every request is refused.

   It removes a file, link, or pipe once it's checked it. A folder is left in `helper/taken/`
   unread and untouched: removing a tree someone else built could make the helper fail, and
   left there it's in nobody's way.
4. It writes `helper/result` saying `state=running`, then runs `./ok3d check` or `./ok3d apply`
   in the ok3d checkout, with no input. A check may take 5 minutes and an apply an hour;
   after that, the helper stops it. Either way, anything it started that's still running in
   its process group is stopped when it ends.
5. It writes its answer to `helper/result`: a few lines, a blank line, then the last 200
   lines `ok3d` printed:

   ```ini
   id=3f9a0c51d2e8b746
   action=check
   state=finished
   exit=0
   finished=2026-10-28T18:05:12Z

   PASS  the settings in ~/ok3d/settings.yaml
   ...
   ```

   A refused request gets `state=refused` and a `reason`, from a fixed list, and one that
   couldn't run gets `state=failed`. If the helper stops partway through (a restart, a
   reboot), it marks that answer `failed` when it starts again, so the page doesn't wait
   for it forever. Every request taken gets an answer. The answer repeats
   nothing the request said except its id, and only when the id is valid (16 to 64 hex
   digits), so the page knows which request was refused.
6. The page reads `helper/result` every few seconds, and shows it when the id matches.

## Saving settings and devices

When you save settings or devices on the Dashboard, it sends the whole file after the head:

```ini
id=9c1e5d0b7a2f4e63
action=save-devices

devices:
  - name: router
    ...
```

1. The helper checks the file is UTF-8 text, at most 64 KB, with no control characters but
   tabs and newlines. If the request has a `base` (the SHA-256 of the file as the page
   showed it, or `none` when there was none), and your file no longer matches it, the save
   is refused: the file changed on the server since the page showed it.
2. It writes it to its own folder, as `helper/staged-devices.yaml`, and runs
   `./ok3d validate devices` on it: the same checks `./ok3d check` runs on yours. The file
   may hold only `devices`, and the devices must pass the chart's schema with your
   settings.
3. Only if that passes does it copy your current file to `local/backups/` in the ok3d
   checkout and put the new one in its place, readable only by you, through a temporary file
   renamed into place. If it fails, your file is unchanged, and the answer says what was
   wrong.

`save-settings` does the same for `settings.yaml`, with `./ok3d validate settings
--from-dashboard`. The file may hold only your own sections, never the chart's own
(`kube-prometheus-stack`, `prometheus-blackbox-exporter`, `gateway`, `global`); it must pass
the schema with your devices; and these settings must stay exactly as they are in yours:

| Setting | Why only you may change it |
|---|---|
| `host` | Where ok3d keeps its data, which the helper and the cluster both depend on |
| `cluster` | The cluster's name, image, ports, and the address the pages are published on |
| `tls` | The domain the certificate authority vouches for |
| `unifi` | Where the UniFi API key is sent, and whether its certificate is checked |
| `alerts.ntfy.server` | Where the ntfy token is sent |
| `alerts.email.smarthost`, `username`, `requireTls` | Where the mail password is sent, and how |
| `modules.remoteAccess`, `mesh`, `agents` | How far ok3d is open to the outside, and what may act on your network |

A setting that's missing counts as different from one set to its default, so adding one
counts as a change too. To change any of these, edit `settings.yaml` on the server.
Everything else (the other modules, how much history to keep, which alerts are on, who email
alerts go to, how often they repeat) the Dashboard may change. Until there's a
`settings.yaml`, the Dashboard can't save settings at all: the first ones are made on the
server.

The last 10 copies of each file are kept.

## Setting a line of .env

The Dashboard never reads `.env`, and the helper never sends a value back. To set one, the
Dashboard sends its name and value:

```ini
id=5b8d2f1c0e7a9346
action=set-env
name=NTFY_TOPIC

ok3d-7f3k9q2m8x
```

- The name must be `UNIFI_API_KEY`, `NTFY_TOPIC`, `NTFY_TOKEN`, or `SMTP_PASSWORD`. A wrong
  value in one of these only stops something working, since where each is sent is a setting
  only you may change. The other three lines of `.env` are yours alone, on the server:
  `OK3D_ADMIN_PASSWORD` (choosing it would let someone sign in to Grafana),
  `ANTHROPIC_API_KEY` (a key of theirs would send the agents' conversations to their
  account), and `DEADMAN_URL` (it could be pointed anywhere).
- The value is one line of at most 1,024 printable characters, without spaces, quotes,
  backslashes, dollar signs, or backticks, so `.env` holds it as plain text. Empty clears it.
  API keys, tokens, URLs, and generated passwords all fit; a password with those characters
  has to go into `.env` by hand.
- The helper keeps every other byte of `.env` as it was. It puts the new value on that
  name's first line and removes any later ones, since `./ok3d` reads the last. It copies
  the old `.env` to `local/backups/` first, and writes the new one readable only by you. It
  won't write through a `.env` that's a link.
- The answer says `Saved NTFY_TOPIC in .env.` and nothing more. The value never reaches the
  answer, the log, or anywhere the Dashboard can read.

`local/backups/` is in the ok3d checkout, which the Dashboard's container never sees, so a
copy of `.env` there stays out of its reach.

## Looking for a release, and upgrading

`look-for-release` runs `./ok3d upgrade` with nothing after it, which asks GitHub for the list
of ok3d's releases (`git ls-remote`). That's all it asks for, except that, like every `./ok3d`
command, it first fetches the charts' dependencies if any are missing. It writes what it found to
`helper/newest-release`, which Home reads:

```ini
checked=2026-10-30T09:00:00Z
newest=v0.5.2
```

`newest=none` when no release is newer. Nothing looks for a release on its own: only this
request, or `./ok3d upgrade` on the server.

`upgrade` names the release:

```ini
id=2d7e4a9c6b1f8053
action=upgrade
version=v0.5.2
```

The version must be `v` and three numbers of up to six digits, exactly. The helper doesn't run
the upgrade itself: partway through, the new release's `./ok3d install` restarts the helper's
service, which stops everything the helper started. So it starts `./ok3d upgrade v0.5.2 --yes`
as a systemd user service of its own, `ok3d-upgrade` (with `systemd-run --user`), with the
helper's `PATH` (the service gets the rest of its environment from your systemd user
session, not from the helper), and answers once that has started. The
answer says the upgrade started, not that it worked; Home follows the upgrade itself.

`./ok3d upgrade` checks everything again, whoever asked:

- The version is a release tag, newer than the checkout's.
- The tag is an annotated tag whose own name is that version, for a commit. A signed tag of
  an older release, pushed again under a newer name, is refused.
- It's signed with an SSH key in `deploy/release-signers`: the copy in the checkout as it is
  before the upgrade, so a release can't vouch for itself. Only SSH signatures count; git
  is told not to check an OpenPGP or X.509 one, which it would check against your own keys.
- The commit it checks out is the one the tag is for, not anything else with the same name,
  and once it's there, its `src/ok3d/__init__.py` must say that version, or it moves back.

Then it backs up, moves, checks, installs, and makes the cluster again, as docs/upgrading.md
describes. It writes how it's going to the helper's folder (below) as it goes. If it won't
upgrade at all (a release that isn't newer, changes of yours to ok3d's own files, a request
the helper is still carrying out), it says why there too when the helper started it (the
helper sets `OK3D_UPGRADE_FROM_DASHBOARD=yes` for it), so Home shows it; a refusal on the
server is shown on the server only. It takes its lock before any of these checks, and writes
a refusal only while it holds the lock, so it never writes over the record of an upgrade
that's running. It won't start while the helper is carrying out another request (an Apply,
say), since it would delete the cluster under it; and once it holds the lock, the helper
starts none.

While an upgrade runs, the helper refuses every request, the Dashboard's Check, Apply, and
saves included, since any of them partway through would race it. It counts an upgrade as
running while the `ok3d-upgrade` service is active, or while something holds a lock on
`local/upgrading` in the ok3d checkout. `./ok3d upgrade` holds that lock (with `flock`) for as
long as it runs, so an upgrade started on the server counts too (including one waiting on the server for you to type yes),
and the system lets go of it when the upgrade ends, however it ends. The helper writes that
a request is running before it asks, and `./ok3d upgrade` takes its lock before it reads
that answer, so whichever comes second sees the other: an Apply never starts under an
upgrade, nor an upgrade under an Apply. A request the helper is about to refuse says it's
running for a moment first, so `./ok3d upgrade` reads a running answer again for a few
seconds before it counts. If `helper/upgrade` says an upgrade is running when
neither is true (the server restarted partway), the helper rewrites it as stopped, keeping
the step it stopped at, so Home doesn't show it running forever. It asks whether one is
running before it reads the file and again after, so an upgrade that finishes or starts in
between is never marked stopped.

## What the helper writes

In `<data root>/helper/`, readable only by you. `result` and `seen` are written to a
temporary file first and renamed into place, so the page never reads half of one.

| File | What's in it |
|---|---|
| `taken/` | Each request while it's checked; afterwards, only folders someone sent |
| `result` | Its answer to the last request (above) |
| `output` | Everything `ok3d` printed for the last request, written as it runs |
| `seen` | The ids of the last 100 requests, so none runs twice |
| `staged-settings.yaml`, `staged-devices.yaml` | A file the Dashboard sent, only while `./ok3d validate` checks it |
| `current-settings.yaml`, `current-devices.yaml` | Copies of yours, for the Dashboard to show; missing when you have none, and never copied through a link. Everything in them, comments too, is visible to the Dashboard, which is one more reason secrets belong in `.env` |
| `env-set` | The names of the lines in `.env` that have a value, one per line. Never a value |
| `applied` | When the last `./ok3d apply` that worked finished, for the Dashboard's What's next. `./ok3d apply` writes it, not the helper, so an Apply on the server counts too, and `./ok3d delete` removes it |
| `newest-release` | When `./ok3d upgrade` last looked for a release, and the newer one it found. `./ok3d` writes it |
| `upgrade` | How the last upgrade went: `from`, `to`, `state` (`running`, `finished`, or `failed`), `step`, `started`, and `finished`. `./ok3d upgrade` writes it; the helper rewrites it only to mark an upgrade that stopped partway |
| `upgrade-output` | Everything the last upgrade printed, written as it runs |
| `alive` | When it last wrote these: every 30 seconds, after every request, and every 30 seconds while a command runs |
| `lock` | Held while the helper runs, so a second one on the same data root won't start |

In the ok3d checkout: `settings.yaml`, `devices.yaml`, and `.env` when you save them, and
`local/backups/`, which keeps the last 10 copies of each from before a save, and a folder of
all three from before each upgrade.

## Running it

`./ok3d install` sets the service up (docs/dashboard-under-the-hood.md says how). To try it
by hand instead, from the ok3d checkout:

```sh
python3 -I src/ok3d/helper.py once --ok3d-dir . --data-root /srv/ok3d    # handle one request
python3 -I src/ok3d/helper.py watch --ok3d-dir . --data-root /srv/ok3d   # keep watching
```

As a service, it logs one line for each request: `journalctl --user -u ok3d-helper -f`. An
upgrade it started logs to its own service: `journalctl --user -u ok3d-upgrade`.
