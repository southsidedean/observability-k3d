# HostDiskFillingUp

**Severity:** warning

A computer's disk is under 20% free and, at the pace of the last 6 hours, will be full within a day.

## What to check

1. Find what's growing: `sudo du -xh --max-depth=2 <mountpoint> | sort -h | tail`.
2. Common causes: logs that never rotate, a download or a backup running, old container images (`docker system df`).
3. Free space before it's full: a full disk stops databases and can corrupt what they were writing.

## When it clears

It clears on its own when the disk stops filling or has more than 20% free.

To keep it quiet while you work on it, add a [maintenance window](../alerts.md#maintenance-windows-keeping-alerts-quiet-while-you-work) on the Dashboard's Maintenance page, or with `./ok3d maintenance` on the server.
