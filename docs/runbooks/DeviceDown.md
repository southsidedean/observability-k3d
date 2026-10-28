# DeviceDown

**Severity:** critical

A device in `devices.yaml` hasn't answered ping for 2 minutes.

## What to check

1. Is it switched on, and are its lights normal? Most often it lost power or was unplugged.
2. Is the device it's `behind` up? If that one is down too, start there: everything behind it is cut off with it.
3. Can another computer on the same network reach it (`ping <address>`)? If it can, the problem is between ok3d's server and the device.
4. Did its address change? A device that gets its address by DHCP can move unless your router reserves one for it.
5. Some devices stop answering ping after a firmware update or a settings change, while working otherwise. If so, switch its check to `tcp:<port>` or `http`.

## When it clears

It clears on its own a minute or two after the device answers again.

To keep it quiet while you work on it, add a silence in Alertmanager. That arrives on the Dashboard in 0.5; until then, [docs/alerts.md](../alerts.md#silencing-an-alert) shows the command.
