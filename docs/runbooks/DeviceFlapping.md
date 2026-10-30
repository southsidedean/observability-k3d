# DeviceFlapping

**Severity:** warning

A device's ping went up and down at least four times in 15 minutes.

## What to check

1. A loose or damaged cable, or a port on its way out: try another cable and another switch port.
2. Power: a failing power supply, or a PoE port at its limit. Check the switch's PoE budget.
3. Wi-Fi at the edge of its range, or interference: move the device or the access point closer.
4. A device that sleeps to save power can look like this. If it's meant to, take `ping` out of its checks.

## When it clears

It clears on its own once the device stays steady.

To keep it quiet while you work on it, add a [maintenance window](../alerts.md#maintenance-windows-keeping-alerts-quiet-while-you-work) on the Dashboard's Maintenance page, or with `./ok3d maintenance` on the server.
