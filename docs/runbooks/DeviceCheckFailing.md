# DeviceCheckFailing

**Severity:** warning

A device answers ping, but one of its other checks (http, https, or tcp:<port>) has failed for 5 minutes. The device is up; a service on it isn't.

## What to check

1. Open the page or connect to the port yourself, from another computer. The alert names the check.
2. If the service is supposed to be off, take that check out of `devices.yaml`.
3. Restart the service, or the device, as you would without ok3d.
4. For https: the check accepts self-signed certificates, so a failure is the page itself, not its certificate.

## When it clears

It clears on its own when the check passes again.

To keep it quiet while you work on it, add a [maintenance window](../alerts.md#maintenance-windows-keeping-alerts-quiet-while-you-work) on the Dashboard's Maintenance page, or with `./ok3d maintenance` on the server.
