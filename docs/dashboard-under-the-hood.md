# The Dashboard under the hood

How the Dashboard is built, as the code stands. It's arriving in parts during 0.5: so far it
has its sign-in and a first page showing ok3d's version and the helper's last answer. The
pages for settings, devices, and Check and Apply come next, and the installer that sets it
all up comes after them. To see how Check and Apply reach the server, read
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

- `--user`: it runs as you, so it can read the helper's answers, which are readable only by
  you. Without it, the image runs as a user with no rights to anything (65532).
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
| `tests.yml`, job `dashboard image` | every pull request | Builds the image, runs it read-only with no capabilities, checks it serves its sign-in page over HTTPS as a non-root user, and scans it |
| `images.yml` | every merge to `main`, and every release tag | Scans both architectures, then publishes them with an SBOM and build provenance, attests the image, and scans it again by digest |
| `image-scan.yml` | weekly | Scans the latest release's image, so CVEs found after a release show up in the Security tab |

A scan that finds a fixable high or critical CVE stops the publish. `.trivyignore` lists any
CVE that may be ignored, with the reason; it's empty.

## Signing in

The Dashboard has a password of its own, not Grafana's admin login, because it has to work
when the cluster is down.

- On first start it makes one, 16 characters with no look-alikes (`kxq7-m2pa-9fht-3bnd`). It
  keeps a salted scrypt hash in `dashboard/password.json` and the password itself in
  `dashboard/password`, both readable only by you, so the installer can show it to you.
- Signing in gives the browser a session cookie that lasts 12 hours: `Secure`, `HttpOnly`,
  and `SameSite=Strict`, so it's never sent with a request from another site. Sessions live
  in memory, so restarting the Dashboard signs everyone out.
- After 5 wrong passwords in 5 minutes, sign-in pauses for a minute, for everyone, since
  there's only one password to guess. Each wrong password also waits half a second.

## Every request

- HTTPS only, TLS 1.2 or newer, with the Dashboard's own certificate
  (`dashboard/tls/dashboard.crt` and `.key`). It won't start without one, and plain HTTP gets
  no answer.
- Every page but the sign-in page needs a session; without one, it sends you to sign in.
- Every form must come with an `Origin` header naming the Dashboard itself, or it's refused.
  A form is read only when it's `application/x-www-form-urlencoded` and at most 4 KB.
- Every page is made in `src/ok3d/dashboard/server.py`, with every value escaped, including
  what `ok3d` printed in the helper's answer.
- Every answer carries the same headers: a Content Security Policy that allows only the
  Dashboard's own stylesheet, no scripts, and no frames, plus `Strict-Transport-Security`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and
  `Cache-Control: no-store`. It names itself `ok3d-dashboard`, without its Python version.
- It logs one line per request: the address, the method, and the path without its query.

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
