# HostDiskAlmostFull

**Severity:** critical

A computer's disk has less than 5% free.

## What to check

1. Free space now: find the biggest folders with `sudo du -xh --max-depth=2 <mountpoint> | sort -h | tail`.
2. Quick wins: old logs (`sudo journalctl --vacuum-size=200M`), old container images (`docker image prune`), and downloads you no longer need.
3. If it's ok3d's own data root, lower `metrics.retentionSize` in `settings.yaml` and `./ok3d apply`.

## When it clears

It clears on its own when the disk has more than 5% free.

To keep it quiet while you work on it, add a [maintenance window](../alerts.md#maintenance-windows-keeping-alerts-quiet-while-you-work) on the Dashboard's Maintenance page, or with `./ok3d maintenance` on the server.
