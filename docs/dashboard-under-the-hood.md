# The Dashboard under the hood

How the Dashboard is built, as the code stands. It's arriving in parts during 0.5: so far it
has its sign-in and five pages (Home, with Check and Apply; Setup; Settings; Devices; and
Keys). The
installer (`./ok3d install`, and `install.sh` for `curl | sh`) sets it all up. To see how a request reaches the server, read
[the helper under the hood](helper-under-the-hood.md).

## Where it runs

The Dashboard runs in a container on the server, outside the k3d cluster, so it keeps
working when the cluster is down or being made again. Its image is
`ghcr.io/southsidedean/ok3d-dashboard`, built for amd64 and arm64. `./ok3d install` starts it
like this (with your data root, domain, and port), every time it runs:

```sh
docker run --detach --name ok3d-dashboard --restart unless-stopped \
  --user "$(id -u):$(id -g)" --read-only --cap-drop ALL --security-opt no-new-privileges \
  --publish 0.0.0.0:8444:8444 \
  --volume /srv/ok3d/dashboard:/state \
  --volume /srv/ok3d/helper:/helper:ro \
  ghcr.io/southsidedean/ok3d-dashboard:0.5.0 --origin https://dashboard.noc.home.arpa:8444
```

Its address is `https://dashboard.<domain>:<cluster.ports.dashboard>`, a name under the same
`*.<domain>` you point at the server for the other pages. The image is this release's, or
`main` for a checkout of main; `OK3D_DASHBOARD_IMAGE` names another, such as one built on the
server to try a change.

- `--user`: it runs as you, so it can read the helper's answers and its own password files,
  which are readable only by you. Without it, the image runs as a user with no rights to
  anything (65532).
- `--read-only`, `--cap-drop ALL`, `no-new-privileges`: it can't change its own files or
  gain any privilege.
- `/state` is `<data root>/dashboard`: its password, its certificate, and the outbox where it
  leaves requests for the helper.
- `--origin`: its own address, so it accepts forms only from pages it served there.
- `/helper` is `<data root>/helper`, read-only: the helper's answers.

It gets no Docker socket and nothing else from the server.

## The image

`Dockerfile.dashboard` builds it on Wolfi, Chainguard's free base, whose packages get
security fixes quickly. The Dashboard uses only Python's standard library, so Python is all
the image adds, with the `ok3d` package from `src/ok3d`.

| Workflow | When | What it does |
|---|---|---|
| `tests.yml`, job `dashboard image` | every pull request | Builds the image, runs it as the installer will (as you, read-only, no capabilities), signs in, opens the first page, and scans it |
| `images.yml` | every merge to `main`, and every release tag | Scans both architectures, then publishes them with an SBOM and build provenance, attests the image, and scans each architecture again by digest |
| `image-scan.yml` | weekly | Scans both architectures of the latest release's image, so CVEs found after a release show up in the Security tab (it skips until the first release with the image) |

A scan that finds a fixable high or critical CVE stops the publish. `.trivyignore` lists any
CVE that may be ignored, with the reason; it's empty.

## Signing in

The Dashboard has a password of its own, not Grafana's admin login, because it has to work
when the cluster is down.

- On first start it makes one, 16 characters with no look-alikes (`kxq7-m2pa-9fht-3bnd`). It
  writes the password to `dashboard/password` first, then a salted scrypt hash to
  `dashboard/password.json`, both readable only by you, so the installer can show it to you.
  If it can't read or write them (the wrong owner, say), it stops with a message rather
  than making a new password.
- Signing in gives the browser a session cookie, `__Host-ok3d_session`, that lasts 12 hours:
  `Secure`, `HttpOnly`, and `SameSite=Strict`. Browsers send it only to this host, and not
  with requests started by other sites. Other pages on the same server count as the same
  site, though, which is why every form is also checked (below). Sessions live in memory, so
  restarting the Dashboard signs everyone out.
- Passwords are checked one at a time. After 5 wrong passwords from one address in 5
  minutes, that address waits a minute, so a device guessing can't lock you out from
  another. After 50 wrong passwords from anywhere in 5 minutes, sign-in pauses for everyone
  for a minute. Each wrong password also waits half a second.

## Every request

- HTTPS only, TLS 1.2 or newer, with the Dashboard's own certificate
  (`dashboard/tls/dashboard.crt` and `.key`). It won't start without one, and plain HTTP gets
  no answer.
- Each connection gets its own thread, and its TLS handshake happens there, so a client that
  connects and says nothing holds up nobody else. A connection has 10 seconds for its
  handshake and between each read and write after it. At most 32 are served at once; more
  are closed straight away.
- Every page but the sign-in page, the stylesheet, and "not found" needs a session; without
  one, it sends you to sign in.
- Every form must come with an `Origin` header naming the Dashboard itself, and, from
  browsers that send it, `Sec-Fetch-Site: same-origin`, or it's refused. A form is read only
  when it's `application/x-www-form-urlencoded`, at most 4 KB (about 200 KB for a settings
  or devices file), with at most 10 fields. No `GET` changes anything. Started with
  `--origin https://my-server.lan:8444` (once for each address you open it at), it accepts
  forms only from those exact addresses, which the installer will pass; without, the Origin
  must match the address the browser asked for.
- Every page is made in `src/ok3d/dashboard/server.py`, with every value escaped, including
  what `ok3d` printed in the helper's answer.
- Every answer carries the same headers: a Content Security Policy that allows only the
  Dashboard's own stylesheet, no scripts, and no frames, plus `X-Content-Type-Options:
  nosniff`, `Referrer-Policy: same-origin`, `Cache-Control: no-store`, and
  `Cross-Origin-Opener-Policy: same-origin`. The referrer policy is `same-origin`, not
  `no-referrer`, because with `no-referrer` browsers send `Origin: null` on a form, which
  the Origin check refuses; other sites still get no referrer. It sends no `Strict-Transport-Security`: that
  would hold for every web page on the server's name, on every port, for a year. It names
  itself `ok3d-dashboard`, without its Python version.
- It logs one line per request: the address, the method, the path without its query, and
  the status. Control characters are escaped, so nothing in a request can rewrite your
  terminal.

## The pages

| Page | What it shows | What it can do |
|---|---|---|
| Home | Whether the helper is running, what's left before ok3d can do its job, What's next once an Apply has worked, and the helper's last answer with what `ok3d` printed | **Check**, and **Apply** once a Check has found no problems |
| Setup | The ready-made setups, a switch for each module, and where alerts go | Choose a setup, or turn one switch on or off |
| Settings | Your `settings.yaml`, as the helper last copied it | Save a changed one |
| Devices | Your `devices.yaml` (or an empty list) | Save a changed one |
| Keys | Which lines of `.env` are set, never their values | Set or clear `UNIFI_API_KEY`, `NTFY_TOPIC`, `NTFY_TOKEN`, or `SMTP_PASSWORD` |

Each page reads only the helper's folder, mounted read-only at `/helper`:

- `current-settings.yaml` and `current-devices.yaml`: the helper's copies of yours.
- `env-set`: the names of the lines in `.env` that have a value.
- `alive`: when the helper last wrote it: every 30 seconds, after every request, and every
  30 seconds while a Check or Apply runs. While it's more than 90 seconds old, the pages say
  the helper isn't running and send nothing.
- `result`: the answer to the last request.
- `applied`: when the last `./ok3d apply` that worked finished, from the Dashboard or on the
  server. `./ok3d apply` writes it, and `./ok3d delete` removes it. Home shows What's next
  while it's there.

Every button leaves one request in `/state/outbox/request`, written to a temporary file and
renamed into place, then sends you to Home, where the answer appears. The Dashboard keeps the
id of the request it last sent in `/state/last-sent`. One request at a time, however many
tabs are open: while ours waits in the outbox, while the helper says it's running one, or
until the answer to the one we last sent arrives (or 10 minutes pass), a new one is refused
with a note to wait. If the outbox can't be written, the page says so and sends nothing.

- **Apply** turns on only when the helper's answer to the last request this Dashboard sent
  is a Check that found no problems. Anything sent since (a save, a key) turns it off again,
  as does a failed Check. The server checks this too, not only the button. It doesn't see
  changes you make to the files on the server after the Check, and the helper doesn't
  enforce it: Apply is something you could run yourself anyway.
- **Saving settings or devices** sends the whole file, with a browser's `\r\n` line endings
  turned into `\n`, at most 64 KB, and the SHA-256 of the file as the page showed it. The
  helper refuses the save if the file has changed on the server since, so an edit there
  isn't overwritten. Then it checks the file with `./ok3d validate` and saves it only if it
  passes. A settings save can't change the settings only you may change on the
  server, and Settings has nothing to save until `settings.yaml` exists on the server.
- **Keys** checks a value the way the helper will (one line of letters, digits, and symbols,
  with no spaces, quotes, backslashes, `$`, or backticks), so a value the helper would
  refuse is never sent. A value is never shown back, not even in an error.

## Setup and its switches

Setup changes `settings.yaml` for you, a switch at a time, and saves it the way Settings
does: the whole file, with the fingerprint of the copy the page showed, through the helper,
which checks it with `./ok3d validate` first. `src/ok3d/dashboard/switches.py` lists the
switches and the setups.

- **The switches** are `modules.*` and `alerts.ntfy.enabled`, `alerts.email.enabled`, and
  `alerts.deadman.enabled`. Each shows its setting as it's written in `settings.yaml`, and
  which `.env` lines it needs. A value Setup can't read as true or false (`yes`, say, which
  Helm reads as true) shows as "can't tell", and the switch can set it. A module that comes
  in a later release says which, with no button. The mesh, remote access, and agents are changed only on the server, like the other
  settings a save from the Dashboard can't change. A switch that needs a setting the
  Dashboard can't set (UniFi needs `unifi.url`, email needs `alerts.email.smarthost`) says so
  until it's there.
- **The setups** are Basic NOC (no modules), Network NOC (UniFi), NOC with logs (0.6), and
  NOC with agents (0.9). Choosing one sets every module switch the Dashboard may change: on
  if the setup has it, off if not. The one your settings match now is marked.
- **Reading and changing the file.** The Dashboard has only Python's own library, which has
  no YAML parser, so `switches.py` follows the file line by line, in the shape
  `settings.example.yaml` has: one key per line, indented with spaces, each mapping at one
  indent. It changes the one line a switch is on, keeping its comment, or adds the switch
  at the end of the mapping it belongs in (adding the mapping too if it's missing). On the
  way to a switch, anything else (flow style like `{unifi: true}`, an anchor or merge key,
  a key written twice, tabs, a quoted key, a value that runs onto the next line) means it
  stops and asks you to use the Settings page. So do a carriage return, a byte order mark,
  or a Unicode line break anywhere in the file (Helm splits lines there, and Python's
  `split("\n")` doesn't), and a block of text (`|` or `>`) in the mapping where a new
  switch would go. Only spaces and tabs count as spaces, as in YAML. Tests check, with a
  real YAML parser, on the example settings and on generated files, that each change means
  the switch it set and nothing else, and that each shape above is refused. Whatever it
  writes still goes through `./ok3d validate`.
- **Nothing is sent** when the settings changed on the server since the page was shown, when
  a switch is one the page doesn't offer, when something it needs is missing, or when the
  settings already say it.

Home's list of what's left comes from the same reading: each switched-on part's `.env` lines
that aren't set and settings it needs, a switch Setup can't read, alerts with nowhere to go
(only when both ntfy and email read as off), and a `devices.yaml` with no devices. What's
next links to Grafana and the certificate authority's page at the domain and port in your
settings, if they look like a domain and a port, and the defaults if not.

## What ./ok3d install does

`./ok3d install` needs Linux with systemd, and runs as you, never as root. It's safe to run
again: it brings each part up to date. In order, it:

1. Reads your settings, and checks the data root is there and that you can write to it. The
   ok3d folder and the data root may have only letters, digits, and `. _ / -`, since the
   service file holds them.
2. Makes `dashboard/`, `dashboard/outbox/`, and `helper/` in the data root, readable only by
   you.
3. Makes ok3d's certificate authority if there's none (the same one the pages use).
4. Issues the Dashboard's certificate from it, for `dashboard.<domain>`, valid for 397 days
   (browsers accept at most 398). The Dashboard's container can write `dashboard/tls/`, so
   nothing there is trusted: the key, the request, and the extensions are made in a new
   folder inside `certs/`, the authority's own, with a random serial, and only the finished
   certificate and key are moved into `tls/` (a rename, which replaces a link there rather
   than following it). A certificate already there is kept only if it's a plain file this
   authority signed for this name, it matches the key beside it, and it has more than 30
   days left.
5. Writes the helper's service, `~/.config/systemd/user/ok3d-helper.service`, from
   `deploy/ok3d-helper.service` with this checkout's paths, through a temporary file, then
   enables and restarts it, so it runs this checkout's code. A `%` or `$` in your `PATH` is
   escaped for systemd; a quote, backslash, or newline there stops the install. Without
   `loginctl enable-linger`, a user's services stop when they log out and don't start at
   boot, so it says to run `sudo loginctl enable-linger <you>` when that's off.
6. Pulls the Dashboard's image first, so a pull that fails leaves the running Dashboard as it
   was, then makes the container again (above).
7. Prints the address. The password is printed the first time only, when the Dashboard has
   just made it; after that, it says which file holds it.

`install.sh`, for `curl -fsSL .../install.sh | sh`, comes before it: it checks out the newest
release (or `OK3D_VERSION`) into `~/ok3d` (or `OK3D_DIR`), makes `settings.yaml` from
`settings.example.yaml` with `OK3D_DATA_ROOT` (default `/srv/ok3d`) if there's none, says
what to run if the data root needs `sudo`, and runs `./ok3d install`. It never uses `sudo`
itself, and never needs a terminal. Everything is inside one function called on its last
line, so a download cut short runs nothing. An existing checkout must be ok3d's, with no
changes of yours to ok3d's own files, and it's moved to the release fetched from the same
place the release was found (`OK3D_REPO`).

## Running it from the checkout

For trying a change without building the image:

```sh
mkdir -p /tmp/dash/state/tls /tmp/dash/helper
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 1 -subj /CN=localhost \
  -keyout /tmp/dash/state/tls/dashboard.key -out /tmp/dash/state/tls/dashboard.crt
.venv/bin/python -m ok3d.dashboard --state /tmp/dash/state --helper /tmp/dash/helper --port 8444
```

Then open `https://localhost:8444/` and sign in with the password in
`/tmp/dash/state/password`.
