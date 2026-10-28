# Alerts

When something on your network needs you, ok3d tells you: on your phone through ntfy, by
email, or both. A dead man's switch tells you when ok3d itself stops. You choose where alerts
go; the alerts themselves come ready-made.

Prometheus checks the alert rules every 30 seconds. When one fires, Alertmanager sends it,
and sends it again while it's still firing: every hour for a critical alert, every 12 hours
for a warning (`alerts.repeatCritical` and `alerts.repeatWarning`). When it clears, you
hear that too. When a device is down, you hear about the device, not also about each of its
checks.

## On your phone, with ntfy

[ntfy](https://ntfy.sh) is a free notification app for iPhone and Android, with no account
to make.

1. Install the ntfy app. Make a topic name nobody could guess, since anyone who knows it can
   read your alerts: `openssl rand -hex 12` makes one. Subscribe to it in the app.
2. In `.env`, set `NTFY_TOPIC` to the topic, and keep the file yours alone:
   `chmod 600 .env`.
3. In `settings.yaml`:

   ```yaml
   alerts:
     ntfy:
       enabled: true
   ```

4. `./ok3d apply`, then `./ok3d test-alert`. The test alert should arrive within a minute.

To use your own ntfy server, set `alerts.ntfy.server`. For a topic that needs a login, set
`alerts.ntfy.useToken: true` and put the token in `.env` as `NTFY_TOKEN`.

## By email

1. In `settings.yaml`:

   ```yaml
   alerts:
     email:
       enabled: true
       to: you@example.com
       from: alerts@example.com
       smarthost: smtp.example.com:587
       username: alerts@example.com
   ```

   `smarthost` is your mail host's server for sending, with its port, usually 587. A mailbox
   of its own for alerts is best: if its password ever leaks, you delete just that one.
2. In `.env`, set `SMTP_PASSWORD` to that mailbox's password.
3. `./ok3d apply`, then `./ok3d test-alert`. The first one may land in spam.

## When ok3d itself stops: the dead man's switch

An alert can't tell you that the computer sending alerts is down. A dead man's switch can:
ok3d sends it a ping every minute, and when the pings stop, it tells you (by email or on
your phone, from its own servers).

1. Make a check at a service such as [healthchecks.io](https://healthchecks.io) (free for a
   few checks), with a period of 1 minute and a grace time of a few minutes. Copy its ping
   address.
2. In `.env`, set `DEADMAN_URL` to that address.
3. In `settings.yaml`:

   ```yaml
   alerts:
     deadman:
       enabled: true
   ```

4. `./ok3d apply`. Within a minute or two, the check shows its first ping.

## The alerts

Every alert links to its runbook: what it means and what to check, in order.

| Alert | Severity | What it means |
|---|---|---|
| [DeviceDown](runbooks/DeviceDown.md) | critical | A device hasn't answered ping for 2 minutes. |
| [DeviceCheckFailing](runbooks/DeviceCheckFailing.md) | warning | One of a device's http, https, or tcp checks has failed for 5 minutes. |
| [DeviceFlapping](runbooks/DeviceFlapping.md) | warning | A device went up and down four times in 15 minutes. |
| [DeviceMetricsDown](runbooks/DeviceMetricsDown.md) | warning | Prometheus can't read a device's metrics. |
| [DeviceCertificateExpiring](runbooks/DeviceCertificateExpiring.md) | warning | A device's certificate runs out within two weeks. |
| [UniFiControllerUnreachable](runbooks/UniFiControllerUnreachable.md) | warning | ok3d can't read your UniFi controller. |
| [UniFiDeviceBusy](runbooks/UniFiDeviceBusy.md) | warning | A UniFi device's processor is above 90%. |
| [UniFiDeviceMemoryFull](runbooks/UniFiDeviceMemoryFull.md) | warning | A UniFi device's memory is above 90%. |
| [HostDiskFillingUp](runbooks/HostDiskFillingUp.md) | warning | A disk will be full within a day. |
| [HostDiskAlmostFull](runbooks/HostDiskAlmostFull.md) | critical | A disk has less than 5% free. |
| [HostMemoryLow](runbooks/HostMemoryLow.md) | warning | A computer is almost out of memory. |
| [HostRaidDegraded](runbooks/HostRaidDegraded.md) | critical | A disk in a software RAID failed. |

Kubernetes' own alerts (a pod that keeps restarting, a volume filling up) come with
kube-prometheus-stack and cover ok3d's own parts.

## Silencing an alert

While you work on something, you can keep its alert quiet. The Dashboard does this from
0.5; until then, from a terminal on the server:

```sh
kubectl --context k3d-ok3d -n monitoring exec alertmanager-ok3d-kube-prometheus-stack-alertmanager-0 \
  -c alertmanager -- amtool silence add alertname=DeviceDown device=printer \
  --comment="Moving the printer" --duration=2h --alertmanager.url=http://localhost:9093
```

Silences are kept in the data root, so they last through a rebuilt cluster.

## If an alert doesn't arrive

Alertmanager's log says why:

```sh
kubectl --context k3d-ok3d -n monitoring logs alertmanager-ok3d-kube-prometheus-stack-alertmanager-0 -c alertmanager
```

`./ok3d check` also says when a destination is on but its secret in `.env` is empty.

## Under the hood

The alert rules are plain Prometheus rule files in `chart/ok3d/rules/`, each with
promtool unit tests in `tests/rules/`. A test holds every rule to metrics its exporter
really serves (recorded in `tests/fixtures/`), so a rule can't silently watch a metric that
doesn't exist. Alertmanager's settings come from `alerts.*` and hold nothing secret: the
secrets are files in the `ok3d-alerts` Secret, which `./ok3d apply` makes from `.env`.
