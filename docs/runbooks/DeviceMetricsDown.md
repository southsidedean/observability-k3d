# DeviceMetricsDown

**Severity:** warning

Prometheus hasn't been able to read a device's metrics port (from `metrics` in `devices.yaml`) for 5 minutes.

## What to check

1. Is the exporter running on the device? For node_exporter: `systemctl status prometheus-node-exporter`.
2. Is its port open to ok3d's server? A firewall on the device (ufw, for one) may block it.
3. Is the port in `devices.yaml` right? node_exporter's is 9100.
4. If the device itself is down, DeviceDown fires too, and this one is held back while it does.

## When it clears

It clears on its own when Prometheus can read the port again.

To keep it quiet while you work on it, add a [maintenance window](../alerts.md#maintenance-windows-keeping-alerts-quiet-while-you-work) on the Dashboard's Maintenance page, or with `./ok3d maintenance` on the server.
