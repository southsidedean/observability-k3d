# UniFiDeviceMemoryFull

**Severity:** warning

A UniFi device's memory has been above 90% for 15 minutes.

## What to check

1. Some UniFi devices run with high memory use as normal. If it's been steady for weeks, raise nothing and watch it.
2. If it keeps climbing, restart the device in the UniFi app, and look for a firmware update that fixes a leak.

## When it clears

It clears on its own when memory use comes down.

To keep it quiet while you work on it, add a silence in Alertmanager. That arrives on the Dashboard in 0.5; until then, [docs/alerts.md](../alerts.md#silencing-an-alert) shows the command.
