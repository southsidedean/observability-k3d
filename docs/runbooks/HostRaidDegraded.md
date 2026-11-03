# HostRaidDegraded

**Severity:** critical

A computer's software RAID is missing a disk: one failed, or mdadm took it out. The array still works, but with no spare: another failure loses data.

## What to check

1. See which disk is missing or failed: `cat /proc/mdstat` and `sudo mdadm --detail /dev/<array>`.
2. Back up anything you can't lose, now, before anything else.
3. Replace the failed disk and add the new one to the array (`sudo mdadm --manage /dev/<array> --add /dev/<new disk>`). The rebuild takes hours.
4. Check the other disks' health while you're there: `sudo smartctl -a /dev/<disk>`.

## When it clears

It clears on its own when the array has all its disks again, once the rebuild finishes.

To keep it quiet while you work on it, add a [maintenance window](../alerts.md#maintenance-windows-keeping-alerts-quiet-while-you-work) on the Dashboard's Maintenance page, or with `./ok3d maintenance` on the server.
