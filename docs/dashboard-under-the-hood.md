# The Dashboard under the hood

How the Dashboard is built, as the code stands. It's arriving in parts during 0.5: so far it
has its sign-in and four pages (Home, with Check and Apply; Settings; Devices; and Keys). The
installer that sets it all up comes next. To see how a request reaches the server, read
[the helper under the hood](helper-under-the-hood.md).

## Where it runs

The Dashboard runs in a container on the server, outside the k3d cluster, so it keeps
working when the cluster is down or being made again. Its image is
`ghcr.io/southsidedean/ok3d-dashboard`, built for amd64 and arm64. The installer starts it
like this:

```sh
docker run -d --name ok3d-dashboard --restart unless-stopped \
  --user "$(id -u):$(id -g)" --read-only --cap-drop ALL --security-opt no-new-privileges \
  -p 8444:8444 \
  -v /srv/ok3d/dashboard:/state \
  -v /srv/ok3d/helper:/helper:ro \
  ghcr.io/southsidedean/ok3d-dashboard:0.5.0
```

- `--user`: it runs as you, so it can read the helper's answers and its own password files,
  which are readable only by you. Without it, the image runs as a user with no rights to
  anything (65532).
- `--read-only`, `--cap-drop ALL`, `no-new-privileges`: it can't change its own files or
  gain any privilege.
- `/state` is `<data root>/dashboard`: its password, its certificate, and the outbox where it
  leaves requests for the helper.
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
  nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, and
  `Cross-Origin-Opener-Policy: same-origin`. It sends no `Strict-Transport-Security`: that
  would hold for every web page on the server's name, on every port, for a year. It names
  itself `ok3d-dashboard`, without its Python version.
- It logs one line per request: the address, the method, the path without its query, and
  the status. Control characters are escaped, so nothing in a request can rewrite your
  terminal.

## The pages

| Page | What it shows | What it can do |
|---|---|---|
| Home | Whether the helper is running, and the helper's last answer with what `ok3d` printed | **Check**, and **Apply** once a Check has found no problems |
| Settings | Your `settings.yaml`, as the helper last copied it | Save a changed one |
| Devices | Your `devices.yaml` (or an empty list) | Save a changed one |
| Keys | Which lines of `.env` are set, never their values | Set or clear `UNIFI_API_KEY`, `NTFY_TOPIC`, `NTFY_TOKEN`, or `SMTP_PASSWORD` |

Each page reads only the helper's folder, mounted read-only at `/helper`:

- `current-settings.yaml` and `current-devices.yaml`: the helper's copies of yours.
- `env-set`: the names of the lines in `.env` that have a value.
- `alive`: when the helper last wrote these (every 30 seconds, and after every request).
  While it's more than 90 seconds old, the pages say the helper isn't running and send
  nothing.
- `result`: the answer to the last request.

Every button leaves one request in `/state/outbox/request`, written to a temporary file and
renamed into place, then sends you to Home, where the answer appears. One request at a time:
while one is waiting or running, a new one is refused with a note to wait.

- **Apply** turns on only when the helper's last answer is a Check that found no problems. A
  save, or a Check that failed, turns it off again, so what's applied is always what was last
  checked. The server checks this too, not only the button.
- **Saving settings or devices** sends the whole file, with a browser's `\r\n` line endings
  turned into `\n`, at most 64 KB. The helper checks it with `./ok3d validate` and saves it
  only if it passes. A settings save can't change the settings only you may change on the
  server, and Settings has nothing to save until `settings.yaml` exists on the server.
- **Keys** checks a value the way the helper will (one line of letters, digits, and symbols,
  with no spaces, quotes, backslashes, `$`, or backticks), so a value the helper would
  refuse is never sent. A value is never shown back, not even in an error.

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
