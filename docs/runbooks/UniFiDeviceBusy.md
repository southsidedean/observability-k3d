# UniFiDeviceBusy

**Severity:** warning

A UniFi device's processor has been above 90% for 15 minutes.

## What to check

1. In the UniFi app, look at what the device is doing: a firmware update, or a lot of traffic.
2. On a gateway, intrusion prevention and traffic identification take a lot of processor. A busy network can keep it high.
3. If it stays high with nothing going on, restart the device in the UniFi app, and look for a firmware update.

## When it clears

It clears on its own when the load comes down.

To keep it quiet while you work on it, add a [maintenance window](../alerts.md#maintenance-windows-keeping-alerts-quiet-while-you-work) on the Dashboard's Maintenance page, or with `./ok3d maintenance` on the server.
