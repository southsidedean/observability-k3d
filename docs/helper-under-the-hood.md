# The helper under the hood

How a click on the Dashboard's **Check** or **Apply** becomes `./ok3d check` or `./ok3d apply`
on the server, and how a change you save on the Dashboard reaches `settings.yaml`,
`devices.yaml`, or `.env`. This page describes the code as it is, in `src/ok3d/helper.py`.

## Why there's a helper

The Dashboard runs in a container. To make the cluster, it would need Docker, and access to
Docker is as good as full control of the server. So the Dashboard gets no Docker and can't
run anything itself. It leaves a request in a file instead, and the helper, a small service
running on the server as you, carries it out.

The helper assumes someone may have taken over the Dashboard's container. The most they can
do through it is run `./ok3d check` or `./ok3d apply`, change the settings the Dashboard is
allowed to change, change your devices, or set one of the lines in `.env.example`. They can't
change where ok3d keeps its data or where it sends your keys, tokens, and passwords, can't
reach the chart's own sections (which choose images and how pods run), and can't read a
secret back.

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
     `action`, and `name` with `set-env`.
   - The id is 16 to 64 lowercase hex digits.
   - The action is one of `check`, `apply`, `save-settings`, `save-devices`, or `set-env`,
     exactly. `check` and `apply` have nothing after their head; the others have a blank line
     and then a body (below).
   - The id isn't one of the last 100 the helper carried out, so a request can't be replayed.

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
   couldn't run gets `state=failed`. Every request taken gets an answer. The answer repeats
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
   tabs and newlines.
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

To change one of those, edit `settings.yaml` on the server. Everything else (the modules,
how much history to keep, which alerts are on, who email alerts go to, how often they
repeat) the Dashboard may change. Before there's a `settings.yaml` at all, at first setup,
there's nothing to keep, so the Dashboard may set them all once.

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

- The name must be one of the lines in `.env.example`: `OK3D_ADMIN_PASSWORD`,
  `UNIFI_API_KEY`, `NTFY_TOPIC`, `NTFY_TOKEN`, `SMTP_PASSWORD`, `DEADMAN_URL`, or
  `ANTHROPIC_API_KEY`.
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
| `lock` | Held while the helper runs, so a second one on the same data root won't start |

In the ok3d checkout: `settings.yaml`, `devices.yaml`, and `.env` when you save them, and
`local/backups/`, which keeps the last 10 copies of each from before a save.

## Running it

The installer sets the service up later in 0.5. Until then, from the ok3d checkout:

```sh
python3 -I src/ok3d/helper.py once --ok3d-dir . --data-root /srv/ok3d    # handle one request
python3 -I src/ok3d/helper.py watch --ok3d-dir . --data-root /srv/ok3d   # keep watching
```

As a service, it logs one line for each request: `journalctl --user -u ok3d-helper -f`.
