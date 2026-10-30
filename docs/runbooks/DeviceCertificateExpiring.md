# DeviceCertificateExpiring

**Severity:** warning

A device's HTTPS certificate runs out in less than two weeks.

## What to check

1. Renew it the way the device does: many renew on their own (Let's Encrypt), some need a new certificate uploaded by hand.
2. For a self-signed certificate, the device's own settings usually have a way to make a new one.
3. If the device renews on its own and the date doesn't move, its renewal is failing: check its logs.

## When it clears

It clears on its own once the device serves a certificate that runs for more than two weeks.

To keep it quiet while you work on it, add a [maintenance window](../alerts.md#maintenance-windows-keeping-alerts-quiet-while-you-work) on the Dashboard's Maintenance page, or with `./ok3d maintenance` on the server.
